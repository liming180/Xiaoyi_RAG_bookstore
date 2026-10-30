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
  QUESTIONS,
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
  return ok({
    token: `mock-token-${Date.now()}`,
    expiresIn: 86400,
    user: { id: 1, username: body.username, displayName: body.username === 'demo' ? '演示用户' : body.username },
  });
});

const profileHandler = http.get(`${BASE}/auth/profile`, () =>
  ok({ id: 1, username: 'demo', displayName: '演示用户' }),
);

/* ------------------------------------------------------------ 会话 */

const listConversations = http.get(`${BASE}/conversations`, () => ok(getState().conversations));

const createConversation = http.post(`${BASE}/conversations`, async ({ request }) => {
  const body = (await request.json().catch(() => ({}))) as { title?: string };
  const conv: Conversation = {
    id: uid('c'),
    title: body.title ?? '新会话',
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

const listQuestions = http.get(`${BASE}/eval/questions`, () => ok(QUESTIONS));

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
    // 首次读取时生成完整结果（模拟异步执行完成）
    const qs = QUESTIONS;
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
  const body = (await request.json().catch(() => ({}))) as { status?: 'accepted' | 'ignored' };
  const st = getState();
  const idx = st.candidates.findIndex((c) => c.id === id);
  if (idx < 0) return fail(40404, '候选不存在', 404);
  st.candidates[idx] = { ...st.candidates[idx]!, status: body.status ?? 'accepted' };
  return ok(null);
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
  const exp = getState().experiments[String(params.id)];
  if (!exp) return fail(40405, '实验不存在', 404);
  return ok(exp);
});

const fetchExperimentReport = http.get(`${BASE}/eval/experiments/:id/report`, ({ params }) => {
  const id = String(params.id);
  const st = getState();
  const exp = st.experiments[id];
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
  startBatch,
  listRuns,
  fetchRun,
  listCandidates,
  decideCandidate,
  createExperiment,
  fetchExperiment,
  fetchExperimentReport,
  submitFeedback,
  feedbackSummary,
];

export { delay, splitText, buildChunks, buildDocuments };
export type { Citation, Message };
