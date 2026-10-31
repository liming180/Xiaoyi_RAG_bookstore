#!/usr/bin/env node
/**
 * P6 全量回归：用真实 Chrome 逐条走验收清单，每条留一张截图。
 *
 * 与 smoke.mjs 的分工：
 *   smoke.mjs   只回答「构建产物能不能起来」——每条路由 dump 一次 DOM，断言关键节点存在。
 *   regress.mjs 回答「验收清单里那些操作路径能不能走通」——要真的发问、真的点引用卡、
 *               真的改参数重建、真的跑一次批量对照。所以它必须能点击和输入，
 *               走 CDP（见 scripts/cdp.mjs）而不是 --dump-dom。
 *
 * 数据来源：本脚本内置一个有状态的 stub 后端（见 stubApi）。不接 MSW 的原因与 smoke
 * 相同（service worker 在 headless 下起不来），但这里还多一个理由：回归要观察
 * 「建库进度从 0 跑到 100」「批量测试从空表变出 10 行」这类状态迁移，
 * 必须有真实的服务端状态在推进，而不是一堆固定 JSON。
 *
 * 用法：node scripts/regress.mjs [--keep] [--only=关键词]
 *   --keep        保留 dist-regress/ 与浏览器 profile
 *   --only=t03    只跑名字里含该关键词的场景（调试用）
 */
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { extname, join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { launchChrome } from './cdp.mjs';

const ROOT = resolve(fileURLToPath(new URL('..', import.meta.url)));
const DIST = join(ROOT, 'dist-regress');
const OUT_DIR = join(ROOT, 'test-artifacts');
const SHOT_DIR = join(OUT_DIR, 'screenshots');
const PROFILE = join(ROOT, '.chrome-regress-profile');
const PORT = 4179;
const ORIGIN = `http://127.0.0.1:${PORT}`;
const KEEP = process.argv.includes('--keep');
const ONLY = process.argv.find((a) => a.startsWith('--only='))?.slice('--only='.length) ?? '';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
};

/* ============================================================ stub 后端状态 */

const DOCS = [
  { id: 'D01', name: '01_活动说明.md', title: '活动说明', tags: ['活动'], charCount: 420, verified: true },
  { id: 'D02', name: '02_借阅规则.md', title: '借阅规则', tags: ['借阅'], charCount: 380, verified: true },
  { id: 'D03', name: '03_空间预约.md', title: '空间预约', tags: ['预约'], charCount: 360, verified: true },
  { id: 'D04', name: '04_期刊与工具书.md', title: '期刊与工具书', tags: ['借阅'], charCount: 340, verified: true },
  { id: 'D05', name: '05_活动调整通知.md', title: '活动调整通知', tags: ['活动'], charCount: 300, verified: true },
  { id: 'D06', name: '06_成员留言摘录.md', title: '成员留言摘录', tags: ['留言'], charCount: 300, verified: false },
];

/** 片段按 180/30 的近似切法预置：每份资料 2–3 条，相邻 start/end 有 30 字重叠。 */
const BASE_CHUNKS = [
  ['D01-C001', 'D01', 0, 34, '星河读书会每月举办一次共读活动，成员可自由参加，场地在社区活动室。'],
  ['D01-C002', 'D01', 25, 55, '共读活动的书目由成员投票决定，每次活动前一周公布。'],
  ['D02-C001', 'D02', 0, 28, '每位成员一次最多借阅 4 本，借期 21 天，可续借一次。'],
  ['D02-C002', 'D02', 20, 46, '逾期未还将暂停借阅资格，续借需在到期前办理。'],
  ['D02-C003', 'D02', 40, 78, '工具书只能在书屋内阅览，不得外借；期刊合订本借期为 7 天。'],
  ['D03-C001', 'D03', 0, 32, '讨论空间需 3 人以上预约，每次最长 2 小时，可提前 2 天预约。'],
  ['D03-C002', 'D03', 24, 58, '预约后不能使用请提前 30 分钟取消，否则计入违约记录。'],
  ['D04-C001', 'D04', 0, 30, '期刊合订本与工具书均不外借，工具书限书屋内查阅。'],
  ['D04-C002', 'D04', 26, 60, '期刊合订本如确需外借，须经管理员登记并 7 天内归还。'],
  ['D05-C001', 'D05', 0, 28, '本周共读活动调整到周六 14:00 开始，16:00 结束。'],
  ['D05-C002', 'D05', 22, 56, '活动地点不变，仍在社区活动室，请提前 10 分钟到场。'],
  ['D06-C001', 'D06', 0, 26, '有成员留言说续借好像可以无限次，这一点尚待核实。'],
  ['D06-C002', 'D06', 20, 54, '另一位成员留言称押金已取消，此说法未在正式资料中出现。'],
];

const QUESTIONS = [
  { id: 'T01', type: '单文档', question: '读书会通常在每周几几点举行？', keywords: '周六|14:00/14点', evidence: '01_活动说明.md' },
  { id: 'T02', type: '单文档', question: '报名最晚什么时候完成？', keywords: '周五|18:00/18点', evidence: '01_活动说明.md' },
  { id: 'T03', type: '单文档', question: '普通图书最多同时借阅几本借多久？', keywords: '4本/四本|21天/二十一天', evidence: '02_借阅规则.md' },
  { id: 'T04', type: '单文档', question: '已经被别人预约的图书还能续借吗？', keywords: '不能/不可以/无法', evidence: '02_借阅规则.md' },
  { id: 'T05', type: '单文档', question: '讨论空间需要几人每次最长多久？', keywords: '3/三|2小时/两小时', evidence: '03_空间预约.md' },
  { id: 'T06', type: '单文档', question: '预约的空间不能使用应提前多久取消？', keywords: '30分钟/半小时', evidence: '03_空间预约.md' },
  { id: 'T07', type: '跨文档', question: '去参加周六读书会活动几点结束同时最多能借几本普通图书？', keywords: '16:00/16点|4本/四本', evidence: '01_活动说明.md与02_借阅规则.md' },
  { id: 'T08', type: '跨文档', question: '报名读书会的截止时间和空间预约可提前的天数分别是什么？', keywords: '周五|2天/两天', evidence: '01_活动说明.md与03_空间预约.md' },
  { id: 'T09', type: '库外', question: '参加读书会要交多少费用？', keywords: '未提供/没有提供/未说明/没有说明/不包含/未提及', evidence: '无' },
  { id: 'T10', type: '库外', question: '管理员的联系电话是多少？', keywords: '未提供/没有提供/未说明/没有说明/不包含/未提及', evidence: '无' },
];

/** 判分：组间 `|` 全中，组内 `/` 命中其一 —— 与 mock 和规格 F09 一致。 */
function judge(answer, keywords) {
  return keywords.split('|').every((group) => group.split('/').some((alt) => answer.includes(alt)));
}

function chunkOf(id) {
  const row = BASE_CHUNKS.find((c) => c[0] === id);
  if (!row) return null;
  const doc = DOCS.find((d) => d.id === row[1]);
  return {
    chunkId: row[0],
    docId: row[1],
    docTitle: doc?.title ?? '',
    headingPath: `# 星河读书会${doc?.title ?? ''}`,
    text: row[4],
    start: row[2],
    end: row[3],
    kind: 'chunk',
    verified: doc?.verified ?? true,
  };
}

function cite(ref, chunkId, score) {
  const c = chunkOf(chunkId);
  return {
    ref,
    chunkId,
    docId: c.docId,
    docTitle: c.docTitle,
    headingPath: c.headingPath,
    text: c.text,
    start: c.start,
    end: c.end,
    score,
    stage: 'rerank',
    kind: 'chunk',
    verified: c.verified,
  };
}

const ANSWERS = {
  T03: {
    content: `根据资料，已登记成员每人最多同时借阅 **4 本**普通图书，每本借期 **21 天** [1]。

需要注意的几点：

- 工具书只能在书屋内阅览，不得外借 [2]
- 普通图书在到期前可申请续借 1 次 [1]
- 已经逾期或被其他成员预约的图书不能续借 [2]

| 项目 | 规则 |
| --- | --- |
| 同时借阅上限 | 4 本 |
| 单本借期 | 21 天 |
| 续借次数 | 1 次 |

以上内容来自《02_借阅规则.md》，仍建议核对原文。`,
    citations: [cite(1, 'D02-C001', 0.87), cite(2, 'D02-C003', 0.71)],
  },
  T07: {
    content: `综合两份资料：周六共读活动 **16:00 结束** [1]；普通图书每人最多同时借 **4 本**，借期 21 天 [2]。

- 活动时间见《01_活动说明.md》与《05_活动调整通知.md》
- 借阅上限见《02_借阅规则.md》`,
    citations: [cite(1, 'D05-C001', 0.9), cite(2, 'D02-C001', 0.82)],
  },
  T09: {
    content: `资料没有提供参加读书会的收费标准。

- 《01_活动说明.md》写明「本文不包含活动收费标准、联系电话和真实身份资料」[1]
- 留言板里有人说「完全免费」，但那只是成员留言，未经核实 [2]

因此无法给出具体金额。`,
    citations: [cite(1, 'D01-C001', 0.79), cite(2, 'D06-C002', 0.62)],
  },
  T10: {
    content: `资料没有提供管理员的联系电话。

- 《01_活动说明.md》明确写了本文不包含联系电话 [1]
- 《03_空间预约.md》也没有提供工作人员电话 [2]

因此无法给出具体号码。`,
    citations: [cite(1, 'D01-C001', 0.76), cite(2, 'D03-C002', 0.58)],
  },
  DEFAULT: {
    content: `根据资料，这一条需要核对原文后回答 [1]。`,
    citations: [cite(1, 'D01-C001', 0.66)],
  },
};

const DIRECT_ANSWERS = {
  T09: '（未引用知识库资料）读书会一般由社区或学校组织，多数是公益性质，通常不收费或只收少量材料费。具体以主办方通知为准。',
  T07: '（未引用知识库资料）读书会活动一般在下午结束，借书数量各馆规定不同，常见是 3–5 本。',
  DEFAULT: '（未引用知识库资料）这个问题需要看具体组织的安排，通常以官方通知为准。',
};

function pickAnswerKey(question) {
  if (question.includes('费用')) return 'T09';
  if (question.includes('联系电话')) return 'T10';
  if (question.includes('几点结束')) return 'T07';
  if (question.includes('借阅几本') || question.includes('借多久')) return 'T03';
  return 'DEFAULT';
}

/** 有状态的后端：消息、建库任务、评测运行都真的存在服务端并推进。 */
function freshState() {
  return {
    conversations: [
      {
        id: 'c-demo',
        title: '演示会话',
        createdAt: 1_700_000_000_000,
        updatedAt: 1_700_000_000_000,
        messageCount: 0,
      },
    ],
    messages: { 'c-demo': [] },
    documents: DOCS.map((d) => ({
      ...d,
      version: 'v1',
      chunkCount: BASE_CHUNKS.filter((c) => c[1] === d.id).length,
      status: 'INDEXED',
      updatedAt: 1_700_000_000_000,
      error: null,
    })),
    indexStatus: {
      status: 'ready',
      chunkSize: 180,
      overlap: 30,
      chunkCount: BASE_CHUNKS.length,
      docCount: DOCS.length,
    },
    tasks: {},
    runs: {},
    experiments: {},
    experimentRuns: {},
    experimentStartedAt: {},
    experimentRunning: false,
    feedback: {},
    seq: 0,
  };
}

const state = freshState();

/**
 * 每条场景开跑前重置服务端状态。
 *
 * 为什么必须重置：场景之间会互相污染。chat-t03 落下的助手消息会让后面的
 * k1-vs-k3 在「等第一条助手回答」时立刻通过 —— 它读到的是上一条旧消息的 trace，
 * 于是断言「k=1 只采用 1 段」量到的是旧消息的 3 段；compare-t09 同理读不到
 * 本轮才产生的 direct 消息。build-progress 把 chunkSize 改成 120 也会让后面
 * 所有场景看到 120/30 而不是 180/30。
 */
function resetState() {
  Object.assign(state, freshState());
}

const nextId = (prefix) => {
  state.seq += 1;
  return `${prefix}-${state.seq}`;
};
const now = () => Date.now();
const ok = (data) => JSON.stringify({ code: 0, message: 'ok', data, timestamp: Date.now() });
const fail = (code, message, http = 200) => ({ body: JSON.stringify({ code, message, data: null }), http });

function sseFrame(event, data) {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

/** 建库任务按时间推进：2.4 秒走完 解析→切分→嵌入→摘要→完成。 */
const TASK_MS = 2400;
function advanceTask(task) {
  const ratio = Math.min(1, (now() - task.startedAt) / TASK_MS);
  task.progress = Math.round(ratio * 100);
  if (ratio >= 1) {
    task.status = 'SUCCEEDED';
    task.stage = 'done';
    task.progress = 100;
    task.chunkCount = Math.round((state.documents.length * 2.5 * 180) / task.chunkSize);
    task.docCount = state.documents.length;
    state.indexStatus = {
      status: 'ready',
      chunkSize: task.chunkSize,
      overlap: task.overlap,
      chunkCount: task.chunkCount,
      docCount: task.docCount,
    };
    state.documents = state.documents.map((d) => ({ ...d, status: 'INDEXED' }));
  } else if (ratio > 0.75) {
    task.stage = 'summarizing';
  } else if (ratio > 0.5) {
    task.stage = 'embedding';
  } else if (ratio > 0.2) {
    task.stage = 'splitting';
  } else {
    task.stage = 'parsing';
  }
  return task;
}

function buildStream(body) {
  const mode = body.mode ?? 'rag';
  const question = body.question ?? '';
  const k = body.k ?? 3;
  const key = pickAnswerKey(question);
  const picked = ANSWERS[key] ?? ANSWERS.DEFAULT;
  const direct = DIRECT_ANSWERS[key] ?? DIRECT_ANSWERS.DEFAULT;
  const conversationId = body.conversationId ?? 'c-demo';
  const messageId = nextId('m');
  const directMessageId = nextId('m');
  const answer = mode === 'direct' ? direct : picked.content;

  const frames = [
    sseFrame('status', { stage: 'rewriting' }),
    sseFrame('status', { stage: 'retrieving' }),
    sseFrame('status', { stage: 'reranking' }),
  ];
  if (mode !== 'direct') frames.push(sseFrame('retrieval', { citations: picked.citations }));
  frames.push(sseFrame('status', { stage: 'generating' }));
  for (let i = 0; i < answer.length; i += 8) {
    frames.push(sseFrame('token', { content: answer.slice(i, i + 8) }));
  }
  frames.push(
    sseFrame('done', {
      messageId,
      usage: { promptTokens: 820, completionTokens: Math.round(answer.length / 1.6) },
      elapsedMs: 2140,
      degraded: false,
      suggestions: mode === 'direct' ? [] : ['续借可以加几天？', '讨论空间能提前几天预约？'],
      directMessageId: mode === 'both' ? directMessageId : undefined,
      directContent: mode === 'both' ? direct : undefined,
    }),
  );

  const traceRows = BASE_CHUNKS.map((c, i) => {
    const chunk = chunkOf(c[0]);
    return {
      rank: i + 1,
      chunkId: chunk.chunkId,
      docId: chunk.docId,
      docTitle: chunk.docTitle,
      headingPath: chunk.headingPath,
      text: chunk.text,
      start: chunk.start,
      end: chunk.end,
      score: Number((0.92 - i * 0.041).toFixed(3)),
      retrieved: i < k,
      kind: 'chunk',
      verified: chunk.verified,
    };
  }).slice(0, Math.max(8, k + 5));

  const list = state.messages[conversationId] ?? (state.messages[conversationId] = []);
  list.push({
    id: nextId('m'),
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
  });
  list.push({
    id: messageId,
    conversationId,
    role: 'assistant',
    content: answer,
    createdAt: now(),
    citations: mode === 'direct' ? [] : picked.citations,
    trace: mode === 'direct' ? null : { question, k, chunkSize: state.indexStatus.chunkSize, overlap: state.indexStatus.overlap, rows: traceRows },
    usage: { promptTokens: 820, completionTokens: 168 },
    elapsedMs: 2140,
    degraded: false,
    suggestions: mode === 'direct' ? [] : ['续借可以加几天？'],
    feedback: null,
  });
  if (mode === 'both') {
    list.push({
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
    });
  }
  const conv = state.conversations.find((c) => c.id === conversationId);
  if (conv) {
    conv.messageCount = list.length;
    conv.updatedAt = now();
    if (conv.title === '新会话' && question) conv.title = question.slice(0, 20);
  }

  return { frames, conversationId };
}

function runEvalBatch(body) {
  const ids = body.questionIds?.length ? body.questionIds : QUESTIONS.map((q) => q.id);  const cases = QUESTIONS.filter((q) => ids.includes(q.id)).map((q, i) => {
    const key = pickAnswerKey(q.question);
    const ragAnswer = (ANSWERS[key] ?? ANSWERS.DEFAULT).content;
    const directAnswer = DIRECT_ANSWERS[key] ?? DIRECT_ANSWERS.DEFAULT;
    const ragPassed = judge(ragAnswer, q.keywords);
    return {
      questionId: q.id,
      type: q.type,
      question: q.question,
      directAnswer,
      directPassed: judge(directAnswer, q.keywords),
      ragAnswer,
      ragPassed,
      ragSources: ragPassed ? ['D02-C001', 'D05-C001'] : [],
      elapsedMs: 1200 + i * 40,
    };
  });
  const stats = {
    total: cases.length,
    passedDirect: cases.filter((c) => c.directPassed).length,
    passedRag: cases.filter((c) => c.ragPassed).length,
  };
  const id = nextId('run');
  const run = {
    id,
    createdAt: now(),
    finishedAt: now(),
    status: 'SUCCEEDED',
    progress: 100,
    stats,
    mode: body.mode ?? 'both',
    k: body.k ?? 3,
    cases,
  };
  state.runs[id] = run;
  return run;
}

/* ------------------------------------------------------------ 参数实验（E3） */

/** 实验进度按时间推进：1.6 秒跑完全部参数组，够让前端轮询看到 0→100。 */
const EXPERIMENT_MS = 1600;

/** 笛卡尔积：与 features/eval/composables/experiment.ts 的 expandAxes 同语义 */
function expandAxes(axes) {
  const out = [];
  for (const chunkSize of axes.chunkSize ?? [180]) {
    for (const overlap of axes.overlap ?? [30]) {
      if (overlap >= chunkSize) continue;
      for (const k of axes.k ?? [3]) {
        for (const rerank of axes.rerank ?? [true]) {
          for (const summary of axes.summary ?? [false]) {
            out.push({ chunkSize, overlap, k, rerank, summary });
          }
        }
      }
    }
  }
  return out;
}

function experimentMetrics(params) {
  return {
    hitRate: Math.min(
      1,
      Number(
        (
          0.62 +
          (params.k - 1) * 0.06 +
          (params.rerank ? 0.08 : 0) +
          (params.summary ? 0.03 : 0)
        ).toFixed(4),
      ),
    ),
    avgElapsedMs: 1500 + params.chunkSize * 2 + (params.rerank ? 400 : 0),
    avgSources: params.k,
    failed: 0,
  };
}

function createExperiment(body) {
  if (state.experimentRunning) return fail(40902, '已有实验在执行', 409);
  const groups = expandAxes(body.axes ?? {});
  if (groups.length === 0) return fail(40004, '参数矩阵为空');
  const id = nextId('exp');
  const exp = {
    id,
    name: body.name || '参数矩阵实验',
    status: 'RUNNING',
    progress: 0,
    totalGroups: groups.length,
    finishedGroups: 0,
    createdAt: now(),
    finishedAt: null,
  };
  state.experiments[id] = exp;
  state.experimentRuns[id] = groups.map((params, i) => ({
    id: `${id}-g${i + 1}`,
    params,
    metrics: experimentMetrics(params),
    elapsedMs: 8000 + i * 500,
  }));
  state.experimentStartedAt[id] = now();
  state.experimentRunning = true;
  return ok(exp);
}

/** 按经过时间推进进度；跑满时置 SUCCEEDED 并解除互斥。幂等。 */
function advanceExperiment(id) {
  const exp = state.experiments[id];
  if (!exp || exp.status !== 'RUNNING') return exp ?? null;
  const startedAt = state.experimentStartedAt[id] ?? now();
  const ratio = Math.min(1, (now() - startedAt) / EXPERIMENT_MS);
  exp.progress = Math.round(ratio * 100);
  exp.finishedGroups = Math.min(exp.totalGroups, Math.floor(ratio * exp.totalGroups));
  if (ratio >= 1) {
    exp.status = 'SUCCEEDED';
    exp.progress = 100;
    exp.finishedGroups = exp.totalGroups;
    exp.finishedAt = now();
    state.experimentRunning = false;
  }
  return exp;
}

function stubApi(pathname, method, bodyText) {
  const path = pathname.replace(/^\/api\/v1/, '');
  const body = bodyText ? JSON.parse(bodyText) : {};

  if (method === 'GET') {
    if (path === '/auth/profile') return ok({ id: 1, username: 'demo', displayName: '演示用户' });
    if (path === '/conversations') return ok(state.conversations);
    const msgMatch = /^\/conversations\/([^/]+)\/messages$/.exec(path);
    if (msgMatch) return ok(state.messages[msgMatch[1]] ?? []);
    const traceMatch = /^\/messages\/([^/]+)\/trace$/.exec(path);
    if (traceMatch) {
      for (const list of Object.values(state.messages)) {
        const hit = list.find((m) => m.id === traceMatch[1]);
        if (hit) return ok(hit.trace);
      }
      return ok(null);
    }
    if (path === '/index/status') return ok(state.indexStatus);
    const taskMatch = /^\/index\/tasks\/([^/]+)$/.exec(path);
    if (taskMatch) {
      const task = state.tasks[taskMatch[1]];
      return task ? ok(advanceTask(task)) : fail(40401, '任务不存在');
    }
    if (path === '/documents') return ok(state.documents);
    if (path === '/chunks') return ok(BASE_CHUNKS.map((c) => chunkOf(c[0])));
    if (path === '/eval/questions') return ok(QUESTIONS);
    if (path === '/eval/runs') return ok(Object.values(state.runs).map(({ cases: _c, ...rest }) => rest));
    const runMatch = /^\/eval\/runs\/([^/]+)$/.exec(path);
    if (runMatch) return ok(state.runs[runMatch[1]] ?? null);
    if (path === '/eval/candidates') return ok([]);
    const expMatch = /^\/eval\/experiments\/([^/]+)\/report$/.exec(path);
    if (expMatch) {
      const exp = advanceExperiment(expMatch[1]);
      return ok({ experiment: exp, runs: state.experimentRuns[expMatch[1]] ?? [] });
    }
    const expOne = /^\/eval\/experiments\/([^/]+)$/.exec(path);
    if (expOne) return ok(advanceExperiment(expOne[1]));
    if (path === '/feedback/summary') return ok({ total: 0, up: 0, down: 0, candidates: 0 });
    return ok(null);
  }

  if (method === 'POST') {
    if (path === '/chat/stream') return { stream: buildStream(body) };
    if (path === '/conversations') {
      const conv = { id: nextId('c'), title: body.title ?? '新会话', createdAt: now(), updatedAt: now(), messageCount: 0 };
      state.conversations.push(conv);
      return ok(conv);
    }
    if (path === '/index/rebuild') {
      const id = nextId('task');
      state.tasks[id] = {
        id,
        status: 'RUNNING',
        stage: 'parsing',
        progress: 0,
        chunkSize: body.chunkSize ?? 180,
        overlap: body.overlap ?? 30,
        docCount: state.documents.length,
        chunkCount: 0,
        error: null,
        startedAt: now(),
      };
      return ok(state.tasks[id]);
    }
    if (path === '/eval/batch') return ok(runEvalBatch(body));
    if (path === '/eval/experiments') return createExperiment(body);
    return ok(null);
  }

  if (method === 'DELETE') {
    const msgMatch = /^\/conversations\/([^/]+)\/messages$/.exec(path);
    if (msgMatch) {
      state.messages[msgMatch[1]] = [];
      const conv = state.conversations.find((c) => c.id === msgMatch[1]);
      if (conv) conv.messageCount = 0;
      return ok(null);
    }
    return ok(null);
  }

  return ok(null);
}

/* ================================================================ 静态服务 */

function startServer() {
  // 提问模式与 k 存在 localStorage（不进 Pinia），所以「切到 k=1」最稳的做法是
  // 从 seed 页写进去再跳转，而不是去点 el-select 的下拉层 —— 后者依赖 popper 的
  // 挂载时序，在无头环境下点击命中率不稳定。
  const seedHtml = (target, theme = 'light', mode = 'rag', k = '3') => `<!doctype html><meta charset="utf-8"><script>
localStorage.setItem('xiaoyi.token', 'regress-token');
localStorage.setItem('xiaoyi.mode', ${JSON.stringify(mode)});
localStorage.setItem('xiaoyi.k', ${JSON.stringify(k)});
localStorage.setItem('xiaoyi.theme', ${JSON.stringify(theme)});
location.replace(${JSON.stringify(target)});
</script>`;

  const server = createServer((req, res) => {
    const url = new URL(req.url ?? '/', ORIGIN);
    const pathname = decodeURIComponent(url.pathname);

    if (pathname === '/__seed.html') {
      const target = url.searchParams.get('to') ?? '/chat';
      res.writeHead(200, { 'Content-Type': MIME['.html'], 'Cache-Control': 'no-store' });
      res.end(
        seedHtml(
          target,
          url.searchParams.get('theme') === 'dark' ? 'dark' : 'light',
          url.searchParams.get('mode') ?? 'rag',
          url.searchParams.get('k') ?? '3',
        ),
      );
      return;
    }

    if (pathname.startsWith('/api/v1')) {
      let bodyText = '';
      req.on('data', (chunk) => {
        bodyText += chunk.toString();
      });
      req.on('end', () => {
        const result = stubApi(pathname, req.method ?? 'GET', bodyText);
        if (result && typeof result === 'object' && 'stream' in result) {
          const { frames } = result.stream;
          res.writeHead(200, {
            'Content-Type': 'text/event-stream; charset=utf-8',
            'Cache-Control': 'no-cache',
            Connection: 'keep-alive',
          });
          let i = 0;
          const timer = setInterval(() => {
            if (i >= frames.length) {
              clearInterval(timer);
              res.end();
              return;
            }
            res.write(frames[i]);
            i += 1;
          }, 6);
          // 必须挂 res 的 close，不能挂 req 的：
          // Node ≥16 的 IncomingMessage 在请求体读完（end 之后）就会发 close，
          // 挂在 req 上会在第一帧之前就把定时器清掉，客户端永远等不到 token。
          res.on('close', () => clearInterval(timer));
          return;
        }
        const payload = typeof result === 'string' ? result : result.body;
        res.writeHead(200, { 'Content-Type': MIME['.json'], 'Cache-Control': 'no-store' });
        res.end(payload);
      });
      return;
    }

    let filePath = join(DIST, normalize(pathname).replace(/^([/\\])+/, ''));
    if (existsSync(filePath) && statSync(filePath).isDirectory()) filePath = join(filePath, 'index.html');
    if (!existsSync(filePath)) filePath = join(DIST, 'index.html');
    if (!existsSync(filePath)) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('dist-regress 缺失，先跑 build');
      return;
    }
    res.writeHead(200, { 'Content-Type': MIME[extname(filePath)] ?? 'application/octet-stream' });
    res.end(readFileSync(filePath));
  });

  return new Promise((resolvePromise, rejectPromise) => {
    server.once('error', rejectPromise);
    server.listen(PORT, '127.0.0.1', () => resolvePromise(server));
  });
}

/* ================================================================== 场景 */

const log = (message) => process.stdout.write(`[regress] ${message}\n`);

function run(cmd, args, options = {}) {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(cmd, args, { cwd: ROOT, shell: false, stdio: ['ignore', 'pipe', 'pipe'], ...options });
    let stdout = '';
    let stderr = '';
    child.stdout?.on('data', (c) => (stdout += c.toString()));
    child.stderr?.on('data', (c) => (stderr += c.toString()));
    child.on('error', rejectPromise);
    child.on('close', (code) => resolvePromise({ code: code ?? 0, stdout, stderr }));
  });
}

/**
 * 场景定义。
 *
 * 每个场景拿到 page 与 shot(name) 两个工具：page 是 CDP 会话（goto/click/type/waitFor），
 * shot 落一张截图并返回字节数。断言失败就抛错，整条场景记为失败。
 */
const SCENARIOS = [
  {
    name: 'knowledge-list',
    title: '知识库资料列表（六态徽标 + 未核实标记）',
    async run(page, shot) {
      await page.goto(`${ORIGIN}/knowledge`);
      await page.waitFor(`!!document.querySelector('[data-testid="document-table"]')`, { label: '资料表' });
      await page.waitFor(
        `document.querySelectorAll('[data-testid^="doc-row-"]').length >= 6`,
        { label: '六份资料' },
      );
      const unverified = await page.evaluate(
        `!!document.querySelector('[data-testid="doc-row-D06"] .badge--warn')`,
      );
      if (!unverified) throw new Error('D06 未核实标记缺失');
      return shot('regress-01-knowledge-list');
    },
  },
  {
    name: 'build-progress',
    title: '建库面板：改参数 → 重建 → 进度跑到完成',
    async run(page, shot) {
      await page.goto(`${ORIGIN}/knowledge`);
      await page.waitFor(`!!document.querySelector('[data-testid="build-panel"]')`, { label: '建库面板' });

      // 把片段长度从 180 点到 240（+10 ×6），应立刻出现「参数已改动」提示（验收清单任务1 第2条）。
      // 两个坑：①el-input-number 的加减按钮由 vRepeatClick 指令驱动，它监听的是
      // mousedown 而不是 click，用 el.click() 完全没反应；②直接改内部 input.value
      // 只会走 handleInput，v-model 要等 change/blur 才提交，时序不稳。
      // 所以这里派发真正的 mousedown（button: 0，指令里对非左键直接 return）。
      for (let i = 0; i < 6; i += 1) {
        const stepped = await page.evaluate(`(() => {
          const btn = document.querySelector('[data-testid="chunk-size-input"] .el-input-number__increase');
          if (!btn) return false;
          btn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }));
          document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, button: 0 }));
          return true;
        })()`);
        if (!stepped) throw new Error('找不到片段长度的加号按钮');
        await new Promise((r) => setTimeout(r, 60));
      }
      await page.waitFor(`!!document.querySelector('[data-testid="build-dirty"]')`, {
        label: '参数已改动提示',
      });
      await shot('regress-02-build-dirty');

      await page.click('[data-testid="build-submit"]');
      await page.waitFor(`!!document.querySelector('[data-testid="build-progress"]')`, { label: '进度条' });
      await shot('regress-03-build-running');

      await page.waitFor(
        `!!document.querySelector('[data-testid="build-summary"]') &&
         /片段\\s*\\d+\\s*条/.test(document.querySelector('[data-testid="build-summary"]').textContent || '')`,
        { timeoutMs: 20000, label: '建库完成摘要' },
      );
      return shot('regress-04-build-done');
    },
  },
  {
    name: 'chat-t03',
    title: 'T03 提问：答出 4 本 / 21 天，带来源编号',
    async run(page, shot) {
      await page.goto(`${ORIGIN}/chat`);
      await page.waitFor(`!!document.querySelector('[data-testid="question-input"]')`, { label: '输入框' });
      await page.type('[data-testid="question-input"]', '普通图书最多同时借阅几本借多久？');
      await page.click('[data-testid="chat-send"]');
      await page.waitFor(
        `document.querySelectorAll('[data-testid="msg-assistant"]').length >= 1 &&
         !document.querySelector('[data-testid="msg-pending"]')`,
        { timeoutMs: 20000, label: '助手回答' },
      );
      const text = await page.evaluate(
        `document.querySelector('[data-testid="msg-assistant"]').textContent || ''`,
      );
      if (!text.includes('4 本') && !text.includes('4本')) throw new Error('回答里没有「4 本」');
      if (!text.includes('21 天') && !text.includes('21天')) throw new Error('回答里没有「21 天」');
      const badges = await page.evaluate(
        `document.querySelectorAll('[data-testid="cite-badge"]').length`,
      );
      if (badges < 2) throw new Error(`引用徽标只有 ${badges} 个`);
      return shot('regress-05-chat-t03');
    },
  },
  {
    name: 'cite-card',
    title: '按编号查看片段：引用卡五要素 + 原文位置',
    async run(page, shot) {
      await page.click('[data-testid="cite-badge"]');
      await page.waitFor(`!!document.querySelector('[data-testid="cite-card-1"]')`, { label: '引用卡' });
      const card = await page.evaluate(
        `document.querySelector('[data-testid="cite-card-1"]').textContent || ''`,
      );
      if (!card.includes('4 本') && !card.includes('4本')) throw new Error('引用卡里没有「4 本」原文');
      if (!card.includes('第') || !card.includes('字')) throw new Error('引用卡缺少原文位置');
      return shot('regress-06-cite-card');
    },
  },
  {
    name: 'k1-vs-k3',
    title: 'k=1 与 k=3 的检索过程对照（F07/F08）',
    async run(page, shot) {
      // k 存在 localStorage，用 seed 页写进去再跳转，比点 el-select 的下拉层稳
      await page.goto(`${ORIGIN}/__seed.html?to=${encodeURIComponent('/chat')}&k=1`);
      await page.waitFor(`!!document.querySelector('[data-testid="question-input"]')`, { label: '输入框' });
      await page.type('[data-testid="question-input"]', '去参加周六读书会活动几点结束同时最多能借几本普通图书？');
      await page.click('[data-testid="chat-send"]');
      await page.waitFor(
        `document.querySelectorAll('[data-testid="msg-assistant"]').length >= 1 &&
         !document.querySelector('[data-testid="msg-pending"]')`,
        { timeoutMs: 20000, label: 'k=1 回答' },
      );
      await page.click('[data-testid="retrieval-trace"] .trace__toggle');
      await page.waitFor(`!!document.querySelector('[data-testid="trace-row-kept"]')`, {
        label: '检索过程表',
      });
      const kept1 = await page.evaluate(
        `document.querySelectorAll('[data-testid="trace-row-kept"]').length`,
      );
      if (kept1 !== 1) throw new Error(`k=1 时应只有 1 段被采用，实际 ${kept1}`);
      const dropped1 = await page.evaluate(
        `document.querySelectorAll('[data-testid="trace-row-dropped"]').length`,
      );
      if (dropped1 < 1) throw new Error('k=1 时应有被淘汰的候选，才能看出前 k 界线');
      await shot('regress-07-chat-trace-k1');

      // 切回 k=3 再问一次：被采用的段数应变成 3
      await page.goto(`${ORIGIN}/__seed.html?to=${encodeURIComponent('/chat')}&k=3`);
      await page.waitFor(`!!document.querySelector('[data-testid="question-input"]')`, { label: '输入框' });
      await page.type('[data-testid="question-input"]', '普通图书最多同时借阅几本借多久？');
      await page.click('[data-testid="chat-send"]');
      await page.waitFor(
        `document.querySelectorAll('[data-testid="msg-assistant"]').length >= 2 &&
         !document.querySelector('[data-testid="msg-pending"]')`,
        { timeoutMs: 20000, label: 'k=3 回答' },
      );
      await page.click('[data-testid="retrieval-trace"] .trace__toggle');
      await page.waitFor(`!!document.querySelector('[data-testid="trace-row-kept"]')`, {
        label: '检索过程表',
      });
      const kept3 = await page.evaluate(
        `document.querySelectorAll('[data-testid="trace-row-kept"]').length`,
      );
      if (kept3 !== 3) throw new Error(`k=3 时应有 3 段被采用，实际 ${kept3}`);
      return shot('regress-08-chat-trace-k3');
    },
  },
  {
    name: 'compare-t09',
    title: 'T09 对照模式：并排显示两种回答，rag 侧说明未提供',
    async run(page, shot) {
      await page.goto(`${ORIGIN}/__seed.html?to=${encodeURIComponent('/chat')}&mode=both`);
      await page.waitFor(`!!document.querySelector('[data-testid="mode-switch"]')`, { label: '模式切换' });
      const selected = await page.evaluate(
        `document.querySelector('[data-testid="mode-switch"] .is-selected')?.textContent || ''`,
      );
      if (!selected.includes('对照')) throw new Error(`模式应为对照，实际「${selected}」`);

      await page.type('[data-testid="question-input"]', '参加读书会要交多少费用？');
      await page.click('[data-testid="chat-send"]');
      await page.waitFor(`!!document.querySelector('[data-testid="compare-pane"]')`, {
        timeoutMs: 20000,
        label: '对照面板',
      });
      // 不能只等左栏的「正在检索…」消失：第一帧 token 一到它就不见了，
      // 此时 done 还没到，右栏的 direct 文案还是空的。
      await page.waitFor(
        `(() => {
           const el = document.querySelector('[data-testid="compare-direct"]');
           return !!el && el.textContent.includes('未引用知识库资料');
         })()`,
        { timeoutMs: 20000, label: '对照右栏结果' },
      );
      const rag = await page.evaluate(
        `document.querySelector('[data-testid="compare-rag"]').textContent || ''`,
      );
      if (!rag.includes('没有提供')) throw new Error('rag 侧没有说明资料未提供');
      // T09 的正解不是「完全不提完全免费」，而是「引用留言但标注未核实」。
      // 断言要盯的是它有没有把未经核实的留言当成结论：必须同时出现「未经核实」。
      if (rag.includes('完全免费') && !rag.includes('未经核实')) {
        throw new Error('rag 侧把未经核实的留言当成了结论');
      }
      const direct = await page.evaluate(
        `document.querySelector('[data-testid="compare-direct"]').textContent || ''`,
      );
      if (!direct.includes('未引用知识库资料')) throw new Error('direct 侧缺少「未引用知识库资料」标记');
      return shot('regress-09-compare-t09');
    },
  },
  {
    name: 'eval-batch',
    title: '批量对照测试：10 题两种回答 + 初判 + 通过数',
    async run(page, shot) {
      await page.goto(`${ORIGIN}/eval`);
      await page.waitFor(`!!document.querySelector('[data-testid="batch-start"]')`, { label: '开始测试按钮' });
      await page.waitFor(
        `document.querySelectorAll('[data-testid^="pick-"]').length >= 10`,
        { label: '10 道题' },
      );
      await page.click('[data-testid="batch-start"]');
      await page.waitFor(
        `document.querySelectorAll('[data-testid^="case-"]').length >= 10`,
        { timeoutMs: 20000, label: '10 行结果' },
      );
      const passedRag = Number(
        await page.evaluate(
          `document.querySelector('[data-testid="stat-rag"] .batch__card-value').textContent.trim()`,
        ),
      );
      const passedDirect = Number(
        await page.evaluate(
          `document.querySelector('[data-testid="stat-direct"] .batch__card-value').textContent.trim()`,
        ),
      );
      if (!(passedRag > passedDirect)) {
        throw new Error(`查资料通过数应明显高于不查资料：rag=${passedRag} direct=${passedDirect}`);
      }
      if (!(await page.evaluate(`!!document.querySelector('[data-testid="batch-hint"]')`))) {
        throw new Error('缺少「初判结果，仍需人工核对」提示');
      }
      return shot('regress-10-eval-batch');
    },
  },
  {
    name: 'eval-experiment',
    title: '参数矩阵实验：创建 → 进度 → 对比表最优行',
    async run(page, shot) {
      await page.goto(`${ORIGIN}/eval?tab=experiment`);
      await page.waitFor(`!!document.querySelector('[data-testid="exp-create"]')`, { label: '实验配置' });
      // 勾一个 k=4，凑出 2 组
      await page.evaluate(`(() => {
        const el = document.querySelector('[data-testid="axis-k-4"]');
        if (!el) return false;
        el.click();
        return true;
      })()`);
      await page.click('[data-testid="exp-create"]');
      await page.waitFor(`!!document.querySelector('[data-testid="exp-compare"]')`, {
        timeoutMs: 20000,
        label: '对比表',
      });
      const best = await page.evaluate(
        `document.querySelectorAll('[data-testid^="exp-row-"][data-best="true"]').length`,
      );
      if (best !== 1) throw new Error(`最优行应恰好 1 条，实际 ${best}`);
      return shot('regress-11-eval-experiment');
    },
  },
  {
    name: 'chunks-overlap',
    title: '片段浏览：相邻片段重叠文字（拓展B）',
    async run(page, shot) {
      await page.goto(`${ORIGIN}/knowledge/chunks`);
      await page.waitFor(`!!document.querySelector('[data-testid="chunk-list"]')`, { label: '片段列表' });
      await page.click('[data-testid="chunk-focus-D02-C001"]');
      await page.waitFor(`!!document.querySelector('[data-testid="overlap-panel"]')`, {
        label: '相邻并排面板',
      });
      const len = await page.evaluate(
        `document.querySelector('[data-testid="overlap-length"]').textContent || ''`,
      );
      if (!/重叠\s*\d+\s*字/.test(len)) throw new Error(`重叠字数文案异常：${len}`);
      return shot('regress-12-chunks-overlap');
    },
  },
  {
    name: 'clear-chat',
    title: '清空对话：确认后消息清空、参数保留（拓展A）',
    async run(page, shot) {
      // 自己造前置状态：seed 成「对照」模式再发一问，
      // 这样断言「清空后模式仍是对照」才有意义，也不依赖上一个场景留下的痕迹。
      await page.goto(`${ORIGIN}/__seed.html?to=${encodeURIComponent('/chat')}&mode=both`);
      await page.waitFor(`!!document.querySelector('[data-testid="question-input"]')`, { label: '输入框' });
      await page.type('[data-testid="question-input"]', '参加读书会要交多少费用？');
      await page.click('[data-testid="chat-send"]');
      await page.waitFor(
        `document.querySelectorAll('[data-testid="msg-assistant"]').length >= 1 &&
         !document.querySelector('[data-testid="msg-pending"]')`,
        { timeoutMs: 20000, label: '已有消息' },
      );
      const before = await page.evaluate(
        `document.querySelectorAll('[data-testid="msg-assistant"]').length`,
      );
      await page.click('[data-testid="clear-chat"]');
      await page.waitFor(`!!document.querySelector('.el-message-box')`, { label: '确认弹窗' });
      await shot('regress-13-clear-confirm');
      await page.evaluate(`(() => {
        const btn = document.querySelector('.el-message-box__btns .el-button--primary');
        btn.click();
        return true;
      })()`);
      await page.waitFor(
        `document.querySelectorAll('[data-testid="msg-assistant"]').length === 0`,
        { timeoutMs: 15000, label: '消息清空' },
      );
      const modeKept = await page.evaluate(
        `document.querySelector('[data-testid="mode-switch"] .is-selected')?.textContent || ''`,
      );
      if (!modeKept.includes('对照')) throw new Error(`清空后模式应保留「对照」，实际「${modeKept}」`);
      // 把清空前的条数记进报告，方便人工复核「确实是从有到无」而不是本来就没消息。
      return shot('regress-14-clear-chat', { assistantsBefore: before });
    },
  },
];

/* ================================================================== 主流程 */

async function main() {
  const startedAt = Date.now();
  mkdirSync(SHOT_DIR, { recursive: true });

  log('构建产物（vite build → dist-regress/）…');
  const build = await run('npx', ['vite', 'build', '--outDir', 'dist-regress', '--emptyOutDir'], {
    shell: true,
  });
  if (build.code !== 0) {
    process.stderr.write(build.stderr || build.stdout);
    throw new Error('回归构建失败');
  }
  log('构建完成');

  const server = await startServer();
  log(`静态服务器 + 有状态 stub 就绪：${ORIGIN}`);

  const chrome = await launchChrome({ profileDir: PROFILE });
  log('Chrome 已就绪');

  const results = [];
  let page = await chrome.openPage();
  try {
    // 先写 token，否则路由守卫会把每条路由都踢回 /login
    await page.goto(`${ORIGIN}/__seed.html?to=${encodeURIComponent('/chat')}`);

    const scenarios = ONLY ? SCENARIOS.filter((s) => s.name.includes(ONLY)) : SCENARIOS;
    if (scenarios.length === 0) throw new Error(`没有匹配 --only=${ONLY} 的场景`);

    for (const scenario of scenarios) {
      const shots = [];
      const shot = async (name, meta) => {
        const file = join(SHOT_DIR, `${name}.png`);
        await page.screenshot(file);
        const bytes = existsSync(file) ? statSync(file).size : 0;
        shots.push({ name, file: `test-artifacts/screenshots/${name}.png`, bytes, meta });
        return bytes;
      };
      try {
        // 每条场景都从干净的服务端状态开跑，见 resetState 的注释
        resetState();
        const bytes = await scenario.run(page, shot);
        const okAll = shots.length > 0 && shots.every((s) => s.bytes > 0);
        results.push({ name: scenario.name, title: scenario.title, ok: okAll, shots });
        log(`${okAll ? 'PASS' : 'FAIL'} ${scenario.title}  截图 ${bytes}B`);
      } catch (error) {
        results.push({
          name: scenario.name,
          title: scenario.title,
          ok: false,
          shots,
          error: error instanceof Error ? error.message : String(error),
        });
        log(`FAIL ${scenario.title}  ${error instanceof Error ? error.message : String(error)}`);
        // 单条失败不终止整轮：剩下的场景还能给出信息，最后统一看报告
        page.close();
        page = await chrome.openPage();
        await page.goto(`${ORIGIN}/__seed.html?to=${encodeURIComponent('/chat')}`);
      }
    }
  } finally {
    page.close();
    await chrome.close();
    server.close();
  }

  const pass = results.length > 0 && results.every((r) => r.ok);
  writeFileSync(
    join(OUT_DIR, 'regress.json'),
    `${JSON.stringify(
      { pass, at: Date.now(), origin: ORIGIN, elapsedMs: Date.now() - startedAt, scenarios: results },
      null,
      2,
    )}\n`,
    'utf8',
  );

  if (!KEEP) rmSync(DIST, { recursive: true, force: true });

  log(pass ? '🎉 回归全部通过' : `❌ 回归存在失败项（${results.filter((r) => !r.ok).length}/${results.length}）`);
  if (!pass) process.exitCode = 1;
}

main().catch((error) => {
  process.stderr.write(`[regress] 失败：${error instanceof Error ? error.stack : String(error)}\n`);
  process.exitCode = 1;
});
