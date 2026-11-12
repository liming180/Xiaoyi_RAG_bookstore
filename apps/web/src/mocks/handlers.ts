import { HttpResponse, http, delay } from 'msw';
import type {
  AnswerMode,
  Citation,
  Conversation,
  DocumentMeta,
  EvalBatchRequest,
  FeedbackRequest,
  IndexTask,
  Message,
  RebuildRequest,
  UploadResult,
} from '@/types/api';
import { SEED_SUGGESTIONS, buildChunks, buildDocuments, splitText } from './data';
import {
  enabledQuestions,
  advanceExperiment,
  buildExperiment,
  cartesian,
  directAnswer,
  getState,
  judge,
  pickAnswer,
} from './state';

/**
 * MSW handlers：覆盖 §7.3 全部对外端点 + 套餐新增端点。
 *
 * 全部返回统一 Result 包装 { code, message, data, timestamp }，
 * 与真实后端保持一致，这样 http.ts 的拆包逻辑在 mock 阶段就被真实检验。
 */

const BASE = '/api/v1';

let seq = 2000;
const uid = (prefix: string): string => {
  seq += 1;
  return `${prefix}-${seq}`;
};

const ok = <T>(data: T) =>
  HttpResponse.json({ code: 0, message: 'success', data, timestamp: Date.now() });

const fail = (code: number, message: string, status = 200) =>
  HttpResponse.json({ code, message, data: null, timestamp: Date.now() }, { status });

const now = () => Date.now();

/* ------------------------------------------------------------ 鉴权 */

const loginHandler = http.post(`${BASE}/auth/login`, async ({ request }) => {
  const body = (await request.json().catch(() => ({}))) as { username?: string; password?: string };
  if (!body.username) return fail(40001, '用户名不能为空');
  // mock 档不校验密码强度：真实后端的 12–72 字节约束是安全底线，mock 只求联调顺畅。
  // 管理端账号固定叫 admin（与真实部署约定一致），其余一律 USER。
  const role = body.username === 'admin' ? 'ADMIN' : 'USER';
  return ok({
    token: `mock-token-${Date.now()}`,
    expiresIn: 86400,
    user: {
      id: role === 'ADMIN' ? 1 : 2,
      username: body.username,
      displayName: body.username === 'demo' ? '演示用户' : body.username,
      role,
    },
  });
});

const profileHandler = http.get(`${BASE}/auth/profile`, () =>
  ok({ id: 1, username: 'demo', displayName: '演示用户', role: 'USER' }),
);

/* ------------------------------------------------------- 管理端 · 用户管理 */

/**
 * mock 用户库。
 *
 * 内存数组模拟真实后端的四条不变量，让前端在没有 Java 的环境里也能把交互跑完整：
 *   1. username 全局唯一（含软删行）；
 *   2. 只有一个 ADMIN，且 admin 行不能被改/重置/删；
 *   3. 删除是软删，行保留但默认不出现在列表；
 *   4. createdAt 用 Unix 秒，与真实契约一致。
 */
interface MockUser {
  id: number;
  username: string;
  displayName: string | null;
  role: 'ADMIN' | 'USER';
  deleted: boolean;
  createdAt: number;
}

const seedUsers = (): MockUser[] => {
  const now = Math.floor(Date.now() / 1000);
  return [
    { id: 1, username: 'admin', displayName: '管理员', role: 'ADMIN', deleted: false, createdAt: now - 86400 * 30 },
    { id: 2, username: 'u01', displayName: '张三', role: 'USER', deleted: false, createdAt: now - 86400 * 12 },
    { id: 3, username: 'u02', displayName: null, role: 'USER', deleted: false, createdAt: now - 86400 * 5 },
    { id: 4, username: 'u03', displayName: '已删用户', role: 'USER', deleted: true, createdAt: now - 86400 * 40 },
  ];
};

let mockUsers: MockUser[] = seedUsers();
let mockUserSeq = 100;

/** 测试用：把 mock 用户库恢复成种子状态。 */
export function resetMockUsers(): void {
  mockUsers = seedUsers();
  mockUserSeq = 100;
}

const listAdminUsers = http.get(`${BASE}/admin/users`, ({ request }) => {
  const url = new URL(request.url);
  const page = Math.max(Number(url.searchParams.get('page') ?? '1'), 1);
  const size = Math.min(Math.max(Number(url.searchParams.get('size') ?? '20'), 1), 100);
  const keyword = (url.searchParams.get('keyword') ?? '').trim().toLowerCase();
  const includeDeleted = url.searchParams.get('includeDeleted') === 'true';

  const filtered = mockUsers
    .filter((u) => includeDeleted || !u.deleted)
    .filter(
      (u) =>
        !keyword ||
        u.username.toLowerCase().startsWith(keyword) ||
        (u.displayName ?? '').toLowerCase().includes(keyword),
    )
    .sort((a, b) => a.createdAt - b.createdAt || a.id - b.id);

  const start = (page - 1) * size;
  return ok({
    items: filtered.slice(start, start + size),
    total: filtered.length,
    page,
    size,
  });
});

/**
 * mock 审计日志。
 *
 * 真实后端的审计是 `UserService` 在业务动作里写入的副作用；mock 档没有那一层，
 * 所以这里在每个写操作成功后手工补一条 —— 否则审计页在 mock 档永远空白，
 * 「筛选/分页/详情」这些交互根本没法在门禁里验。
 *
 * detail 只记「变了什么」，绝不记密码值：与真实后端同一条纪律。
 */
interface MockAudit {
  id: number;
  operatorId: number;
  action: string;
  target: string;
  detailJson: string;
  createdAt: number;
}

let mockAudits: MockAudit[] = [];
let mockAuditSeq = 0;

/** mock 里的操作者固定是 admin（只有它有权调这些接口）。 */
const MOCK_OPERATOR_ID = 1;

function pushAudit(action: string, target: string, detail: Record<string, unknown>): void {
  mockAuditSeq += 1;
  mockAudits.unshift({
    id: mockAuditSeq,
    operatorId: MOCK_OPERATOR_ID,
    action,
    target,
    detailJson: JSON.stringify(detail),
    createdAt: Math.floor(Date.now() / 1000),
  });
}

/** 测试用：把 mock 审计库清空。 */
export function resetMockAudits(): void {
  mockAudits = [];
  mockAuditSeq = 0;
}

const createAdminUser = http.post(`${BASE}/admin/users`, async ({ request }) => {
  const body = (await request.json().catch(() => ({}))) as {
    username?: string;
    password?: string;
    displayName?: string;
  };

  if (!body.username || !/^[a-zA-Z0-9_]{1,64}$/.test(body.username)) {
    return fail(40001, '用户名需为 1-64 位字母、数字或下划线', 400);
  }
  const bytes = new TextEncoder().encode(body.password ?? '').length;
  if (bytes < 12 || bytes > 72) {
    return fail(40001, '密码长度需为 12-72 个字节（UTF-8）', 400);
  }
  // 重名连软删行一起挡：真实后端的唯一键也包含软删行
  if (mockUsers.some((u) => u.username === body.username)) {
    return fail(40905, '用户名已存在', 409);
  }

  mockUserSeq += 1;
  const created: MockUser = {
    id: mockUserSeq,
    username: body.username,
    displayName: body.displayName?.trim() ? body.displayName.trim() : null,
    role: 'USER', // 永远 USER：接口造不出第二个管理员
    deleted: false,
    createdAt: Math.floor(Date.now() / 1000),
  };
  mockUsers.push(created);
  pushAudit('admin.user.create', `user:${created.id}`, { username: created.username });
  return ok(created);
});

/** 管理端对 admin 行的三类操作统一拒绝，与真实后端 40906 一致。 */
const guardAdminRow = (id: number): ReturnType<typeof fail> | null => {
  const target = mockUsers.find((u) => u.id === id && !u.deleted);
  if (!target) return fail(40409, '用户不存在', 404);
  if (target.role === 'ADMIN') return fail(40906, '不能对管理员账号执行该操作', 409);
  return null;
};


const updateAdminUser = http.put(`${BASE}/admin/users/:id`, async ({ params, request }) => {
  const id = Number(params.id);
  const blocked = guardAdminRow(id);
  if (blocked) return blocked;

  const body = (await request.json().catch(() => ({}))) as { displayName?: string };
  const target = mockUsers.find((u) => u.id === id) as MockUser;
  target.displayName = body.displayName?.trim() ? body.displayName.trim() : null;
  pushAudit('admin.user.update', `user:${id}`, { displayName: 'changed' });
  return ok(target);
});

const resetAdminUserPassword = http.put(`${BASE}/admin/users/:id/password`, async ({ params, request }) => {
  const id = Number(params.id);
  const blocked = guardAdminRow(id);
  if (blocked) return blocked;

  const body = (await request.json().catch(() => ({}))) as { newPassword?: string };
  const bytes = new TextEncoder().encode(body.newPassword ?? '').length;
  if (bytes < 12 || bytes > 72) {
    return fail(40001, '密码长度需为 12-72 个字节（UTF-8）', 400);
  }
  const target = mockUsers.find((u) => u.id === id) as MockUser;
  pushAudit('admin.user.reset-password', `user:${id}`, { password: 'changed' });
  return ok(target);
});

const deleteAdminUser = http.delete(`${BASE}/admin/users/:id`, ({ params }) => {
  const id = Number(params.id);
  const blocked = guardAdminRow(id);
  if (blocked) return blocked;

  const target = mockUsers.find((u) => u.id === id) as MockUser;
  target.deleted = true; // 软删：行保留，默认列表中消失
  pushAudit('admin.user.delete', `user:${id}`, { deleted: true });
  return ok(null);
});

/* ------------------------------------------------------- 管理端 · 审计日志 */

const listAdminAudits = http.get(`${BASE}/admin/audit-logs`, ({ request }) => {
  const url = new URL(request.url);
  const page = Math.max(Number(url.searchParams.get('page') ?? '1'), 1);
  const size = Math.min(Math.max(Number(url.searchParams.get('size') ?? '20'), 1), 100);
  const action = (url.searchParams.get('action') ?? '').trim();
  const operatorRaw = (url.searchParams.get('operatorId') ?? '').trim();
  const keyword = (url.searchParams.get('keyword') ?? '').trim().toLowerCase();

  if (operatorRaw && !/^\d+$/.test(operatorRaw)) {
    return fail(40001, '参数不合法', 400);
  }
  const operatorId = operatorRaw ? Number(operatorRaw) : null;

  const filtered = mockAudits
    .filter((a) => !action || a.action === action)
    .filter((a) => operatorId === null || a.operatorId === operatorId)
    .filter((a) => !keyword || a.target.toLowerCase().includes(keyword));

  const start = (page - 1) * size;
  const items = filtered.slice(start, start + size).map((a) => {
    const operator = mockUsers.find((u) => u.id === a.operatorId);
    return {
      id: a.id,
      operatorId: a.operatorId,
      operatorName: operator ? operator.username : null,
      action: a.action,
      target: a.target,
      detailJson: a.detailJson,
      createdAt: a.createdAt,
    };
  });

  return ok({ items, total: filtered.length, page, size });
});

const listAdminAuditActions = http.get(`${BASE}/admin/audit-logs/actions`, () => {
  const actions = [...new Set(mockAudits.map((a) => a.action))].sort();
  return ok(actions);
});

/* ------------------------------------------------------------ 会话 */

const listConversations = http.get(`${BASE}/conversations`, () => ok(getState().conversations));

const createConversation = http.post(`${BASE}/conversations`, async ({ request }) => {
  const body = (await request.json().catch(() => ({}))) as { title?: unknown };
  // 真实后端是 `CreateConversationRequest(String title)`：title 不是字符串就直接
  // 反序列化失败回 400/40001。mock 必须同样严格，否则「请求体形状错了」这类
  // 只有真机才暴露的缺陷会在门禁里全绿（历史上就发生过：{"title":{"title":"…"}}）。
  if (body.title !== undefined && typeof body.title !== 'string') {
    return fail(40001, '请求体格式不合法', 400);
  }
  const conv: Conversation = {
    id: uid('c'),
    title: body.title || '新会话',
    createdAt: now(),
    updatedAt: now(),
    messageCount: 0,
  };
  getState().conversations.unshift(conv);
  getState().messages[conv.id] = [];
  return ok(conv);
});

const deleteConversation = http.delete(`${BASE}/conversations/:id`, ({ params }) => {
  const id = String(params.id);
  const st = getState();
  st.conversations = st.conversations.filter((c) => c.id !== id);
  delete st.messages[id];
  return ok(null);
});

const listMessages = http.get(`${BASE}/conversations/:id/messages`, ({ params }) => {
  const id = String(params.id);
  return ok(getState().messages[id] ?? []);
});

/** F10 清空对话：删消息，保留会话与参数 */
const clearMessages = http.delete(`${BASE}/conversations/:id/messages`, ({ params }) => {
  const id = String(params.id);
  const st = getState();
  st.messages[id] = [];
  const conv = st.conversations.find((c) => c.id === id);
  if (conv) conv.messageCount = 0;
  return ok(null);
});

const fetchTrace = http.get(`${BASE}/messages/:id/trace`, ({ params }) => {
  const id = String(params.id);
  const st = getState();
  for (const list of Object.values(st.messages)) {
    const msg = list.find((m) => m.id === id);
    if (msg) return ok(msg.trace);
  }
  return ok(null);
});

/* --------------------------------------------------------- SSE 对话 */

function sseFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function buildStream(mode: AnswerMode, question: string, k: number, conversationId: string) {
  const { content, citations, trace } = pickAnswer(question, k);
  const direct = directAnswer(question);
  const messageId = uid('m');
  const directMessageId = uid('m');

  const encoder = new TextEncoder();
  const frames: string[] = [];
  frames.push(sseFrame('status', { stage: 'rewriting' }));
  frames.push(sseFrame('status', { stage: 'retrieving' }));
  frames.push(sseFrame('status', { stage: 'reranking' }));
  if (mode !== 'direct') {
    frames.push(sseFrame('retrieval', { citations }));
  }
  frames.push(sseFrame('status', { stage: 'generating' }));

  const answer = mode === 'direct' ? direct : content;
  // 按 6 字一段切，模拟真实 token 流
  for (let i = 0; i < answer.length; i += 6) {
    frames.push(sseFrame('token', { content: answer.slice(i, i + 6) }));
  }

  frames.push(
    sseFrame('done', {
      messageId,
      usage: { promptTokens: 820, completionTokens: Math.round(answer.length / 1.6) },
      elapsedMs: 2100,
      degraded: false,
      suggestions: mode === 'direct' ? [] : SEED_SUGGESTIONS,
      directMessageId: mode === 'both' ? directMessageId : undefined,
      directContent: mode === 'both' ? direct : undefined,
    }),
  );

  // 落库
  const st = getState();
  const list = st.messages[conversationId] ?? (st.messages[conversationId] = []);
  const userMsg: Message = {
    id: uid('m'),
    conversationId,
    role: 'user',
    content: question,
    createdAt: now(),
    citations: [],
    trace: null,
    usage: null,
    elapsedMs: null,
    degraded: false,
    suggestions: [],
    feedback: null,
  };
  const assistantMsg: Message = {
    id: messageId,
    conversationId,
    role: 'assistant',
    content: mode === 'direct' ? direct : content,
    createdAt: now(),
    citations: mode === 'direct' ? [] : citations,
    trace: mode === 'direct' ? null : { question, k, chunkSize: 180, overlap: 30, rows: trace },
    usage: { promptTokens: 820, completionTokens: 168 },
    elapsedMs: 2100,
    degraded: false,
    suggestions: mode === 'direct' ? [] : SEED_SUGGESTIONS,
    feedback: null,
  };
  list.push(userMsg, assistantMsg);

  if (mode === 'both') {
    const directMsg: Message = {
      id: directMessageId,
      conversationId,
      role: 'assistant',
      content: direct,
      createdAt: now(),
      citations: [],
      trace: null,
      usage: { promptTokens: 120, completionTokens: 90 },
      elapsedMs: 900,
      degraded: true,
      suggestions: [],
      feedback: null,
    };
    list.push(directMsg);
  }

  const conv = st.conversations.find((c) => c.id === conversationId);
  if (conv) {
    conv.messageCount = list.length;
    conv.updatedAt = now();
    if (conv.title === '新会话' && question) conv.title = question.slice(0, 20);
  }

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      for (const frame of frames) {
        controller.enqueue(encoder.encode(frame));
        await new Promise((r) => setTimeout(r, 2));
      }
      controller.close();
    },
  });

  return new HttpResponse(stream, {
    headers: {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    },
  });
}

const chatStream = http.post(`${BASE}/chat/stream`, async ({ request }) => {
  const body = (await request.json().catch(() => ({}))) as {
    conversationId?: string;
    question?: string;
    mode?: AnswerMode;
    k?: number;
  };
  const st = getState();
  if (st.experimentRunning) {
    return fail(40901, '实验进行中，提问暂不可用', 409);
  }
  const conversationId = body.conversationId ?? st.conversations[0]?.id ?? 'c-demo';
  if (!st.messages[conversationId]) st.messages[conversationId] = [];
  return buildStream(body.mode ?? 'rag', body.question ?? '', body.k ?? 3, conversationId);
});

/* ------------------------------------------------------------ 资料 */

const listDocuments = http.get(`${BASE}/documents`, () => ok(getState().documents));

const uploadDocuments = http.post(`${BASE}/documents`, async ({ request }) => {
  const form = await request.formData();
  // 注意：jsdom 下 request.formData() 返回的 File 来自 undici，与全局 File 不是同一个构造器，
  // 用 instanceof File 会把上传的文件全部过滤掉。这里只排除字符串字段。
  const files = form.getAll('files').filter((f): f is File => typeof f !== 'string');
  const st = getState();
  const accepted: DocumentMeta[] = [];
  const skipped: UploadResult['skipped'] = [];

  for (const file of files) {
    const lower = file.name.toLowerCase();
    if (!lower.endsWith('.md') && !lower.endsWith('.txt')) {
      skipped.push({ name: file.name, reason: '只接受 .md / .txt 文件' });
      continue;
    }
    if (file.size > 2 * 1024 * 1024) {
      skipped.push({ name: file.name, reason: '文件超过 2MB' });
      continue;
    }
    const text = await file.text();
    if (text.trim() === '') {
      skipped.push({ name: file.name, reason: '文件没有正文' });
      continue;
    }
    const id = uid('D');
    const doc: DocumentMeta = {
      id,
      name: file.name,
      title: file.name.replace(/\.(md|txt)$/i, ''),
      tags: [],
      version: 'v1',
      charCount: text.length,
      chunkCount: 0,
      status: 'INDEXED',
      verified: !/06_成员留言/.test(file.name),
      updatedAt: now(),
      error: null,
    };
    st.documents.push(doc);
    accepted.push(doc);
  }

  // 资料变更 → 待重建（F03）
  if (accepted.length > 0) {
    st.indexStatus = { ...st.indexStatus, status: 'needs_rebuild', reason: '资料已变更' };
    st.documents = st.documents.map((d) =>
      d.status === 'INDEXED' ? { ...d, status: 'NEEDS_REBUILD' } : d,
    );
  }

  return ok({ accepted, skipped });
});

const updateDocument = http.put(`${BASE}/documents/:id`, async ({ params, request }) => {
  const id = String(params.id);
  const patch = (await request.json().catch(() => ({}))) as Partial<DocumentMeta>;
  const st = getState();
  const idx = st.documents.findIndex((d) => d.id === id);
  if (idx < 0) return fail(40401, '资料不存在', 404);
  const next = { ...st.documents[idx]!, ...patch, updatedAt: now() } as DocumentMeta;
  st.documents[idx] = next;
  return ok(next);
});

const deleteDocument = http.delete(`${BASE}/documents/:id`, ({ params }) => {
  const id = String(params.id);
  const st = getState();
  const doc = st.documents.find((d) => d.id === id);
  if (!doc) return fail(40401, '资料不存在', 404);
  st.documents = st.documents.filter((d) => d.id !== id);
  st.chunks = st.chunks.filter((c) => c.docId !== id);
  st.indexStatus = { ...st.indexStatus, status: 'needs_rebuild', reason: `已删除 ${doc.name}` };
  return ok(null);
});

/* ------------------------------------------------------------ 建库 */

const indexStatus = http.get(`${BASE}/index/status`, () => ok(getState().indexStatus));

const rebuildIndex = http.post(`${BASE}/index/rebuild`, async ({ request }) => {
  const body = (await request.json().catch(() => ({}))) as RebuildRequest;
  const chunkSize = body.chunkSize ?? 180;
  const overlap = body.overlap ?? 30;
  if (chunkSize < 50 || chunkSize > 1000) return fail(40002, '片段长度需在 50-1000 之间');
  if (overlap < 0 || overlap >= chunkSize) return fail(40003, '重叠字数必须小于片段长度');

  const st = getState();
  const id = uid('task');
  const chunks = buildChunks(chunkSize, overlap);
  const docs = buildDocuments(chunkSize, overlap);
  const task: IndexTask = {
    id,
    status: 'RUNNING',
    stage: 'parsing',
    progress: 5,
    chunkSize,
    overlap,
    docCount: docs.length,
    chunkCount: 0,
    error: null,
    startedAt: now(),
    finishedAt: null,
  };
  // 记录期望参数，供 fetchIndexTask 在任务完成时同步知识库状态
  st.tasks[id] = task;
  st.pendingRebuild = { chunkSize, overlap, startedAt: now() };
  st.chunks = chunks;

  return ok(task);
});

/** 按已过时间把任务推进到对应阶段（纯函数，便于测试） */
export function progressTask(task: IndexTask, elapsed: number, totalChunks: number): IndexTask {
  const DURATION = 900;
  if (elapsed >= DURATION) {
    return { ...task, status: 'SUCCEEDED', stage: 'done', progress: 100, chunkCount: totalChunks, finishedAt: task.startedAt + DURATION };
  }
  const ratio = Math.max(0, Math.min(1, elapsed / DURATION));
  const stage =
    elapsed > 700 ? 'summarizing' : elapsed > 400 ? 'embedding' : elapsed > 200 ? 'splitting' : 'parsing';
  return {
    ...task,
    status: 'RUNNING',
    stage,
    progress: Math.round(ratio * 100),
    chunkCount: Math.round(totalChunks * ratio),
  };
}

const fetchIndexTask = http.get(`${BASE}/index/tasks/:id`, ({ params }) => {
  const id = String(params.id);
  const st = getState();
  const base = st.tasks[id];
  if (!base) return fail(40402, '任务不存在', 404);

  const totalChunks = buildChunks(base.chunkSize, base.overlap).length;
  const task = progressTask(base, now() - base.startedAt, totalChunks);
  st.tasks[id] = task;

  // 终态时同步知识库状态（参数变化也算需要同步）
  if (
    task.status === 'SUCCEEDED' &&
    (st.indexStatus.status !== 'ready' ||
      st.indexStatus.chunkSize !== task.chunkSize ||
      st.indexStatus.overlap !== task.overlap)
  ) {
    const chunks = buildChunks(task.chunkSize, task.overlap);
    st.chunks = chunks;
    st.indexStatus = {
      status: 'ready',
      docCount: st.documents.length,
      chunkCount: chunks.length,
      chunkSize: task.chunkSize,
      overlap: task.overlap,
      embeddingModel: 'text-embedding-3-small (mock)',
      lastBuiltAt: now(),
      reason: null,
    };
    st.documents = st.documents.map((d) =>
      d.status === 'NEEDS_REBUILD'
        ? { ...d, status: 'INDEXED', chunkCount: chunks.filter((c) => c.docId === d.id).length }
        : d,
    );
  }
  return ok(task);
});

/* ------------------------------------------------------------ 片段 */

const listChunks = http.get(`${BASE}/chunks`, ({ request }) => {
  const url = new URL(request.url);
  const docId = url.searchParams.get('docId');
  const q = url.searchParams.get('q');
  const kind = url.searchParams.get('kind');
  let items = getState().chunks;
  if (docId) items = items.filter((c) => c.docId === docId);
  if (kind) items = items.filter((c) => c.kind === kind);
  if (q) items = items.filter((c) => c.text.includes(q));
  return ok(items);
});

/* ------------------------------------------------------------ 评测 */

const listQuestions = http.get(`${BASE}/eval/questions`, () => ok(enabledQuestions()));

/* ------------------------------------------------- P5-08 题库管理（mock） */

const listAllQuestions = http.get(`${BASE}/eval/questions/all`, () =>
  ok(getState().questions),
);

const createQuestion = http.post(`${BASE}/eval/questions`, async ({ request }) => {
  const body = (await request.json().catch(() => ({}))) as {
    code?: string;
    type?: string;
    question?: string;
    keywords?: string;
    evidence?: string;
  };
  const st = getState();
  if (!body.question || body.question.trim() === '') return fail(40001, '题面不能为空', 400);
  const type = body.type ?? 'single';
  const prefix = type === 'single' ? 'S' : type === 'cross' ? 'X' : 'O';
  let code = body.code?.trim() ?? '';
  if (code === '') {
    // 自动编号：从 S001 起找第一个空位，与后端 nextCode 同口径。
    for (let i = 1; i < 9999; i++) {
      const candidate = `${prefix}${String(i).padStart(3, '0')}`;
      if (!st.questions.some((q) => q.id === candidate)) {
        code = candidate;
        break;
      }
    }
  } else if (st.questions.some((q) => q.id === code)) {
    return fail(40904, `题号已存在: ${code}`, 409);
  }
  const row = {
    id: code,
    type,
    question: body.question.trim(),
    keywords: body.keywords ?? '',
    evidence: body.evidence ?? '',
    enabled: true,
    source: 'manual',
  };
  st.questions.push(row);
  return ok(row);
});

const updateQuestionHandler = http.put(`${BASE}/eval/questions/:code`, async ({ params, request }) => {
  const body = (await request.json().catch(() => ({}))) as {
    type?: string;
    question?: string;
    keywords?: string;
    evidence?: string;
  };
  const st = getState();
  const code = String(params.code);
  const row = st.questions.find((q) => q.id === code);
  if (!row) return fail(40408, `题目不存在: ${code}`, 404);
  if (!body.question || body.question.trim() === '') return fail(40001, '题面不能为空', 400);
  row.type = body.type ?? row.type;
  row.question = body.question.trim();
  row.keywords = body.keywords ?? '';
  row.evidence = body.evidence ?? '';
  return ok(row);
});

const toggleQuestionEnabled = http.post(
  `${BASE}/eval/questions/:code/enabled`,
  async ({ params, request }) => {
    const body = (await request.json().catch(() => ({}))) as { enabled?: boolean };
    const st = getState();
    const code = String(params.code);
    const row = st.questions.find((q) => q.id === code);
    if (!row) return fail(40408, `题目不存在: ${code}`, 404);
    row.enabled = Boolean(body.enabled);
    return ok(row);
  },
);

const deleteQuestionHandler = http.delete(`${BASE}/eval/questions/:code`, ({ params }) => {
  const st = getState();
  const code = String(params.code);
  const row = st.questions.find((q) => q.id === code);
  if (!row) return fail(40408, `题目不存在: ${code}`, 404);
  if (row.source === 'seed') return fail(40001, '内置题不能删除，可以改成停用', 400);
  st.questions = st.questions.filter((q) => q.id !== code);
  return ok(null);
});

const exportQuestions = http.get(`${BASE}/eval/questions/export`, () => {
  const st = getState();
  const lines = ['\ufeff题号,类型,问题,关键词,证据文件'];
  for (const q of st.questions) {
    lines.push(`${q.id},${q.type},${q.question},${q.keywords},${q.evidence}`);
  }
  return new HttpResponse(lines.join('\r\n'), {
    status: 200,
    headers: { 'Content-Type': 'text/csv;charset=UTF-8' },
  });
});

const importQuestions = http.post(`${BASE}/eval/questions/import`, async ({ request }) => {
  const body = (await request.json().catch(() => ({}))) as { csv?: string };
  const st = getState();
  const csv = body.csv ?? '';
  if (csv.trim() === '') return fail(40001, 'CSV 内容为空', 400);
  let created = 0;
  let skipped = 0;
  const errors: string[] = [];
  const rows = csv.replace(/^\ufeff/, '').split(/\r?\n/);
  rows.forEach((line, i) => {
    if (line.trim() === '') return;
    if (i === 0 && (line.includes('题号') || line.includes('问题'))) return;
    const cells = line.split(',');
    if (cells.length < 3) {
      skipped++;
      errors.push(`第 ${i + 1} 行：列数不足`);
      return;
    }
    const code = cells[0].trim();
    if (st.questions.some((q) => q.id === code)) {
      skipped++;
      errors.push(`第 ${i + 1} 行：题号已存在 ${code}`);
      return;
    }
    const rawType = cells[1].trim();
    const type =
      rawType === '单文档' || rawType === 'single'
        ? 'single'
        : rawType === '跨文档' || rawType === 'cross'
          ? 'cross'
          : 'out';
    st.questions.push({
      id: code,
      type,
      question: cells[2].trim(),
      keywords: cells[3]?.trim() ?? '',
      evidence: cells[4]?.trim() ?? '',
      enabled: true,
      source: 'import',
    });
    created++;
  });
  return ok({ created, skipped, errors });
});

const startBatch = http.post(`${BASE}/eval/batch`, async ({ request }) => {
  const body = (await request.json().catch(() => ({}))) as EvalBatchRequest;
  const st = getState();
  const id = uid('run');
  const run = {
    id,
    createdAt: now(),
    finishedAt: now() + 800,
    status: 'SUCCEEDED' as const,
    progress: 100,
    stats: null,
    mode: body.mode ?? 'both',
    k: body.k ?? 3,
    // 用户勾选了哪几题就只跑哪几题；不传则让 GET 时按筛选条件算。
    questionIds: body.questionIds ?? [],
    // 筛选条件记在 run 上：GET 时没有请求体，条件必须留在这里才复现得出来。
    types: body.types ?? [],
    limit: body.limit ?? null,
    sample: body.sample ?? false,
    cases: [],
  };
  st.runs[id] = run as never;
  return ok(run);
});

const listRuns = http.get(`${BASE}/eval/runs`, () =>
  ok(Object.values(getState().runs).map(({ cases: _cases, ...rest }) => rest)),
);

const fetchRun = http.get(`${BASE}/eval/runs/:id`, ({ params }) => {
  const id = String(params.id);
  const st = getState();
  const run = st.runs[id];
  if (!run) return fail(40403, '评测记录不存在', 404);

  if (run.cases.length === 0) {
    // 首次读取时生成完整结果（模拟异步执行完成）。
    // 只跑用户勾选的那几题 —— 与 F09「选问题集」一致，不传才是 T01–T13 全量。
    const wanted = (run as unknown as { questionIds?: string[] }).questionIds;
    // P5-08：没点选题号时按 types/limit/sample 筛选，与真实后端 selectQuestions 同口径。
    const spec = run as unknown as {
      types?: string[];
      limit?: number | null;
      sample?: boolean;
    };
    let pool = enabledQuestions();
    if (spec.types?.length) pool = pool.filter((q) => q.type && spec.types!.includes(q.type));
    if (spec.sample) pool = [...pool].sort(() => Math.random() - 0.5);
    if (spec.limit && spec.limit > 0) pool = pool.slice(0, spec.limit);
    const qs = wanted?.length ? pool.filter((q) => wanted.includes(q.id)) : pool;
    const cases = qs.map((q) => {
      const rag = pickAnswer(q.question, run.k).content;
      const direct = directAnswer(q.question);
      return {
        questionId: q.id,
        type: q.type,
        question: q.question,
        directAnswer: direct,
        directPassed: judge(direct, q.keywords),
        ragAnswer: rag,
        ragPassed: judge(rag, q.keywords),
        ragSources: pickAnswer(q.question, run.k).citations.map((c) => c.chunkId),
        elapsedMs: 1200,
      };
    });
    run.cases = cases as never;
    run.stats = {
      total: cases.length,
      passedDirect: cases.filter((c) => c.directPassed).length,
      passedRag: cases.filter((c) => c.ragPassed).length,
    } as never;
    st.runs[id] = run;
  }
  return ok(run);
});

const listCandidates = http.get(`${BASE}/eval/candidates`, () => ok(getState().candidates));

const decideCandidate = http.post(`${BASE}/eval/candidates/:id/decision`, async ({ params, request }) => {
  const id = String(params.id);
  const body = (await request.json().catch(() => ({}))) as {
    status?: 'accepted' | 'ignored';
    keywords?: string;
  };
  const st = getState();
  const idx = st.candidates.findIndex((c) => c.id === id);
  if (idx < 0) return fail(40404, '候选不存在', 404);
  const status = body.status ?? 'accepted';
  /**
   * N4：关键词只在 accepted 时写入，且「不带」与「传空串」语义不同 ——
   * 不带 = 没动过这个字段（保留原值），空串 = 用户清空了输入框（按没补处理）。
   * 这里如实模拟后端，否则前端的「补完再改状态」这条路径在 mock 档永远测不出来。
   */
  const next = { ...st.candidates[idx]!, status };
  if (status === 'accepted' && body.keywords !== undefined) {
    next.keywords = body.keywords.trim();
  }
  st.candidates[idx] = next;
  return ok(null);
});

/**
 * 已采纳候选导出为题库 CSV。
 *
 * 必须回真的 `text/csv`（不是信封）：前端用 `responseType: 'blob'` 接，Mock 回 JSON 时
 * 拿到的会是「包装成 Blob 的 JSON 文本」，`downloadBlob` 照样能存盘，测试却看不出错 ——
 * 所以这里连 BOM 与转义一起照抄后端实现。
 */
const exportCandidates = http.get(`${BASE}/eval/candidates/export`, () => {
  const rows = getState().candidates.filter((c) => c.status === 'accepted');
  const quote = (value: string): string =>
    /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
  const lines = ['question,keywords'];
  for (const row of rows) {
    lines.push(`${quote(row.question)},${quote(row.keywords ?? '')}`);
  }
  return new HttpResponse(`\uFEFF${lines.join('\r\n')}\r\n`, {
    status: 200,
    headers: { 'Content-Type': 'text/csv;charset=UTF-8' },
  });
});

const createExperiment = http.post(`${BASE}/eval/experiments`, async ({ request }) => {
  const body = (await request.json().catch(() => ({}))) as {
    name?: string;
    axes?: Parameters<typeof cartesian>[0];
  };
  const st = getState();
  if (st.experimentRunning) return fail(40902, '已有实验在执行', 409);
  const axes = body.axes ?? {
    chunkSize: [180],
    overlap: [30],
    k: [3],
    rerank: [true],
    summary: [false],
  };
  if (cartesian(axes).length === 0) return fail(40004, '参数矩阵为空');
  const exp = buildExperiment(body.name ?? '参数实验', axes);
  return ok(exp);
});

const fetchExperiment = http.get(`${BASE}/eval/experiments/:id`, ({ params }) => {
  // 每次轮询按真实流逝时间推进进度：前端 1s 拉一次就能看到 0%→100%，
  // 跑完后 experimentRunning 自动放开，提问恢复。
  const exp = advanceExperiment(String(params.id));
  if (!exp) return fail(40405, '实验不存在', 404);
  return ok(exp);
});

const fetchExperimentReport = http.get(`${BASE}/eval/experiments/:id/report`, ({ params }) => {
  const id = String(params.id);
  const st = getState();
  const exp = advanceExperiment(id);
  if (!exp) return fail(40405, '实验不存在', 404);
  return ok({ experiment: exp, runs: st.experimentRuns[id] ?? [] });
});

/* ------------------------------------------------------------ 反馈 */

const submitFeedback = http.post(`${BASE}/messages/:id/feedback`, async ({ params, request }) => {
  const id = String(params.id);
  const body = (await request.json().catch(() => ({}))) as FeedbackRequest;
  const st = getState();
  st.feedback[id] = body.rating;
  for (const list of Object.values(st.messages)) {
    const msg = list.find((m) => m.id === id);
    if (msg) msg.feedback = body.rating;
  }
  if (body.rating === 'down') {
    const owner = Object.values(st.messages).flat().find((m) => m.id === id);
    const question =
      Object.values(st.messages)
        .flat()
        .filter((m) => m.conversationId === owner?.conversationId && m.role === 'user')
        .at(-1)?.content ?? '（未知问题）';
    st.candidates.unshift({
      id: uid('cand'),
      question,
      source: 'feedback',
      status: 'pending',
      createdAt: now(),
      keywords: null,
    });
  }
  return ok(null);
});

const feedbackSummary = http.get(`${BASE}/feedback/summary`, () => {
  const st = getState();
  const values = Object.values(st.feedback);
  return ok({
    total: values.length,
    up: values.filter((v) => v === 'up').length,
    down: values.filter((v) => v === 'down').length,
    candidates: st.candidates.filter((c) => c.status === 'pending').length,
  });
});

/* --------------------------------------------------------- 导出 */

export const handlers = [
  loginHandler,
  profileHandler,
  loginHandler,
  profileHandler,
  listAdminUsers,
  createAdminUser,
  updateAdminUser,
  resetAdminUserPassword,
  deleteAdminUser,
  listAdminAudits,
  listAdminAuditActions,
  listConversations,
  createConversation,
  deleteConversation,
  listMessages,
  clearMessages,
  fetchTrace,
  chatStream,
  listDocuments,
  uploadDocuments,
  updateDocument,
  deleteDocument,
  indexStatus,
  rebuildIndex,
  fetchIndexTask,
  listChunks,
  listQuestions,
  listAllQuestions,
  createQuestion,
  updateQuestionHandler,
  toggleQuestionEnabled,
  deleteQuestionHandler,
  exportQuestions,
  importQuestions,
  startBatch,
  listRuns,
  fetchRun,
  listCandidates,
  decideCandidate,
  exportCandidates,
  createExperiment,
  fetchExperiment,
  fetchExperimentReport,
  submitFeedback,
  feedbackSummary,
];

export { delay, splitText, buildChunks, buildDocuments };
export type { Citation, Message };
