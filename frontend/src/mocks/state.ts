import type {
  Citation,
  Conversation,
  DocumentMeta,
  EvalCandidate,
  EvalCaseResult,
  EvalQuestion,
  EvalRun,
  Experiment,
  ExperimentParams,
  ExperimentRun,
  IndexStatus,
  IndexTask,
  Message,
  TraceRow,
} from '@/types/api';
import {
  DIRECT_FALLBACK_ANSWER,
  SEED_DOCS,
  SEED_QUESTIONS,
  SEED_SUGGESTIONS,
  T03_ANSWER,
  T10_ANSWER,
  T11_ANSWER,
  T12_ANSWER,
  T13_ANSWER,
  buildChunks,
  buildDocuments,
  seedCitations,
  seedTrace,
} from './data';
import type { ChunkItem } from '@/types/api';

/**
 * MSW 内存数据库。
 *
 * 全部状态放在模块级单例里，handlers 只做「读写这个对象」，
 * 这样 mock 行为与真实后端足够接近：上传后列表变、建库后状态灯变、清空后消息没了。
 */

export interface MockState {
  conversations: Conversation[];
  messages: Record<string, Message[]>;
  documents: DocumentMeta[];
  chunks: ChunkItem[];
  indexStatus: IndexStatus;
  tasks: Record<string, IndexTask>;
  runs: Record<string, EvalRun>;
  experiments: Record<string, Experiment>;
  experimentRuns: Record<string, ExperimentRun[]>;
  candidates: EvalCandidate[];
  feedback: Record<string, 'up' | 'down'>;
  seq: number;
  /** 当前是否有实验在跑（409 互斥用） */
  experimentRunning: boolean;
  /** 一次参数实验跑完需要多久（ms）。测试里调小，避免真等 4 秒 */
  experimentDuration: number;
  /** 每个实验的起始时间戳，用来按流逝时间算进度 */
  experimentStartedAt: Record<string, number>;
  /** 最近一次重建请求的参数与起始时间 */
  pendingRebuild: { chunkSize: number; overlap: number; startedAt: number } | null;
}

const now = Date.now();

function initialState(): MockState {
  const docs = buildDocuments(180, 30);
  const chunks = buildChunks(180, 30);
  const conv: Conversation = {
    id: 'c-demo',
    title: '读书会规则咨询',
    createdAt: now - 3600_000,
    updatedAt: now - 60_000,
    messageCount: 0,
  };

  const welcome: Message = {
    id: 'm-welcome',
    conversationId: conv.id,
    role: 'assistant',
    content: T03_ANSWER,
    createdAt: now - 120_000,
    citations: seedCitations(1),
    trace: {
      question: '普通图书最多同时借阅几本借多久？',
      k: 3,
      chunkSize: 180,
      overlap: 30,
      rows: seedTrace('普通图书最多同时借阅几本借多久？', 3),
    },
    usage: { promptTokens: 820, completionTokens: 168 },
    elapsedMs: 2340,
    degraded: false,
    suggestions: SEED_SUGGESTIONS,
    feedback: null,
  };
  conv.messageCount = 1;

  return {
    conversations: [conv],
    messages: { [conv.id]: [welcome] },
    documents: docs,
    chunks,
    indexStatus: {
      status: 'ready',
      docCount: docs.length,
      chunkCount: chunks.length,
      chunkSize: 180,
      overlap: 30,
      embeddingModel: 'text-embedding-3-small (mock)',
      lastBuiltAt: now - 86_400_000,
      reason: null,
    },
    tasks: {},
    runs: {},
    experiments: {},
    experimentRuns: {},
    candidates: [
      {
        id: 'cand-1',
        question: '参加读书会要交多少费用？',
        source: 'feedback',
        status: 'pending',
        createdAt: now - 7200_000,
        keywords: null,
      },
    ],
    feedback: {},
    seq: 1000,
    experimentRunning: false,
    // 4 秒跑完一组参数实验：既能让进度条真的动起来，又不至于把测试拖长。
    // 测试里可直接改 getState().experimentDuration = 200 来加速。
    experimentDuration: 4000,
    experimentStartedAt: {},
    pendingRebuild: null,
  };
}

let state: MockState = initialState();

export function getState(): MockState {
  return state;
}

export function resetState(): void {
  state = initialState();
}

export function nextId(prefix: string): string {
  state.seq += 1;
  return `${prefix}-${state.seq}`;
}

/* --------------------------------------------------------------- 工具 */

export const QUESTIONS: EvalQuestion[] = SEED_QUESTIONS;

/** F09 判分：每个 | 分组至少命中一个 / 分隔的候选词 */
export function judge(answer: string, keywords: string): boolean {
  if (!keywords) return false;
  return keywords
    .split('|')
    .every((group) => group.split('/').some((alt) => alt.trim() !== '' && answer.includes(alt.trim())));
}

/** 依据问题挑一份最像的种子回答，让 mock 有「检索到了」的实感 */
export function pickAnswer(question: string, k: number, chunkSize = 180, overlap = 30): {
  content: string;
  citations: Citation[];
  trace: TraceRow[];
} {
  const q = question ?? '';
  const isFee = /费用|收费|多少钱|价格/.test(q);
  const isPhone = /电话|号码|联系/.test(q);
  // T11/T12/T13 必须在 isBorrow 之前判：这三题的题干里也带「借」「本」，
  // 落到 isBorrow 分支会拿到 T03 的答案，判分关键词一条都对不上。
  const isPeriodical = /期刊/.test(q);
  const isAdjustment = /11月14日|那一周|调整|有什么变化/.test(q);
  const isRumor = /老成员|听说|6本|六本/.test(q);
  const isBorrow = /借|本|天|续借/.test(q);

  if (isFee || isPhone) {
    const citations = seedCitations(0, chunkSize, overlap).slice(0, Math.min(k, 2));
    return {
      content: T10_ANSWER,
      citations: citations.map((c, i) => ({ ...c, ref: i + 1 })),
      trace: seedTrace(q, k, chunkSize, overlap),
    };
  }

  if (isPeriodical) {
    return {
      content: T11_ANSWER,
      citations: seedCitations(3, chunkSize, overlap).slice(0, k),
      trace: seedTrace(q, k, chunkSize, overlap),
    };
  }

  if (isAdjustment) {
    return {
      content: T12_ANSWER,
      citations: seedCitations(4, chunkSize, overlap).slice(0, k),
      trace: seedTrace(q, k, chunkSize, overlap),
    };
  }

  if (isRumor) {
    // 留言类问题：引 D06（未核实留言）+ D02（正式规则），答案必须先否定再给规则
    const rumor = seedCitations(5, chunkSize, overlap).slice(0, 1);
    const rule = seedCitations(1, chunkSize, overlap).slice(0, 1);
    const citations = [...rumor, ...rule].map((c, i) => ({ ...c, ref: i + 1 }));
    return { content: T13_ANSWER, citations, trace: seedTrace(q, k, chunkSize, overlap) };
  }

  if (isBorrow) {
    const citations = seedCitations(1, chunkSize, overlap).slice(0, k);
    return { content: T03_ANSWER, citations, trace: seedTrace(q, k, chunkSize, overlap) };
  }

  return {
    content: `根据资料，星河读书会每周六 14:00 至 16:00 在观澜书屋二层 A 区开展读书交流，每场最多 12 人，报名截止时间为活动前一日即周五 18:00 [1]。

- 参加者应提前 10 分钟到场 [1]
- 每人分享时间控制在 3 分钟内 [1]
- 临时不能参加时应在报名表中取消 [1]`,
    citations: seedCitations(0, chunkSize, overlap).slice(0, k),
    trace: seedTrace(q, k, chunkSize, overlap),
  };
}

export function directAnswer(question: string): string {
  return `${DIRECT_FALLBACK_ANSWER}\n\n（问题：${question}）`;
}

export function newRun(
  questionIds: string[],
  mode: 'rag' | 'direct' | 'both',
  k: number,
): EvalRun {
  const id = nextId('run');
  const cases: EvalCaseResult[] = questionIds.map((qid) => {
    const q = QUESTIONS.find((x) => x.id === qid);
    const keywords = q?.keywords ?? '';
    const question = q?.question ?? qid;
    const ragAnswer = pickAnswer(question, k).content;
    const direct = directAnswer(question);
    return {
      questionId: qid,
      type: q?.type ?? '',
      question,
      directAnswer: direct,
      directPassed: judge(direct, keywords),
      ragAnswer,
      ragPassed: judge(ragAnswer, keywords),
      ragSources: pickAnswer(question, k).citations.map((c) => c.chunkId),
      elapsedMs: 1200 + Math.round(Math.random() * 900),
    };
  });

  const passedDirect = cases.filter((c) => c.directPassed).length;
  const passedRag = cases.filter((c) => c.ragPassed).length;

  const run: EvalRun = {
    id,
    createdAt: Date.now(),
    finishedAt: Date.now() + 1000,
    status: 'SUCCEEDED',
    progress: 100,
    stats: { total: cases.length, passedDirect, passedRag },
    mode,
    k,
    cases,
  };
  state.runs[id] = run;
  return run;
}

export function cartesian(axes: {
  chunkSize: number[];
  overlap: number[];
  k: number[];
  rerank: boolean[];
  summary: boolean[];
}): ExperimentParams[] {
  const out: ExperimentParams[] = [];
  for (const chunkSize of axes.chunkSize) {
    for (const overlap of axes.overlap) {
      if (overlap >= chunkSize) continue;
      for (const k of axes.k) {
        for (const rerank of axes.rerank) {
          for (const summary of axes.summary) {
            out.push({ chunkSize, overlap, k, rerank, summary });
          }
        }
      }
    }
  }
  return out;
}

/**
 * 创建一次参数实验。
 *
 * 与早期版本的区别：这里只把实验置为 RUNNING 并记录 `startedAt`，真正的进度推进交给
 * `advanceExperiment()` —— 由 `GET /eval/experiments/:id` 每次被轮询时按真实流逝时间推进。
 * 这样前端能真的看到 0%→100% 的进度条，而不是一次跳到 SUCCEEDED。
 */
export function buildExperiment(name: string, axes: Parameters<typeof cartesian>[0]): Experiment {
  const id = nextId('exp');
  const groups = cartesian(axes);
  const exp: Experiment = {
    id,
    name,
    status: 'RUNNING',
    progress: 0,
    totalGroups: groups.length,
    finishedGroups: 0,
    createdAt: Date.now(),
    finishedAt: null,
    error: null,
  };
  state.experiments[id] = exp;
  state.experimentStartedAt[id] = Date.now();
  state.experimentRunning = true;

  state.experimentRuns[id] = groups.map((params, i) => ({
    id: `${id}-g${i + 1}`,
    params,
    metrics: {
      hitRate: Math.min(1, 0.62 + (params.k - 1) * 0.06 + (params.rerank ? 0.08 : 0) + (params.summary ? 0.03 : 0)),
      avgElapsedMs: 1500 + params.chunkSize * 2 + (params.rerank ? 400 : 0),
      avgSources: params.k,
      failed: 0,
    },
    elapsedMs: 8000 + i * 500,
  }));
  return exp;
}

/**
 * 按流逝时间推进实验进度（幂等，可被反复调用）。
 *
 * 用「时间」而不是「调用次数」来推进，是为了让 1s 轮询与真实耗时对齐：测试里把
 * `experimentDuration` 调小即可立刻跑完，页面里则按 4s 匀速走完。
 * 到 100% 时把全局互斥开关 `experimentRunning` 放开，提问随之恢复。
 */
export function advanceExperiment(id: string): Experiment | null {
  const exp = state.experiments[id];
  if (!exp) return null;
  if (exp.status !== 'RUNNING') return exp;

  const startedAt = state.experimentStartedAt[id] ?? exp.createdAt;
  const duration = Math.max(1, state.experimentDuration);
  const ratio = Math.min(1, (Date.now() - startedAt) / duration);

  exp.progress = Math.round(ratio * 100);
  exp.finishedGroups = Math.min(exp.totalGroups, Math.floor(ratio * exp.totalGroups));

  if (ratio >= 1) {
    exp.status = 'SUCCEEDED';
    exp.progress = 100;
    exp.finishedGroups = exp.totalGroups;
    exp.finishedAt = Date.now();
    state.experimentRunning = false;
  }
  return exp;
}

export { SEED_DOCS };
