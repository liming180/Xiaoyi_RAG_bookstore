import type {
  EvalBatchRequest,
  EvalCandidate,
  EvalQuestion,
  EvalRun,
  EvalRunSummary,
  Experiment,
  ExperimentAxis,
  ExperimentReport,
  ExperimentRun,
  FeedbackRequest,
  FeedbackSummary,
} from '@/types/api';
import { get, post } from '../http';

/* ---------------------------------------------------------------- 题目 */

export async function listQuestions(): Promise<EvalQuestion[]> {
  const raw = await get<unknown>('/eval/questions');
  const items = Array.isArray(raw) ? raw : ((raw as { items?: unknown[] })?.items ?? []);
  return items.map((item, i) => {
    const o = (item ?? {}) as Record<string, unknown>;
    return {
      id: String(o.id ?? o.编号 ?? `T${String(i + 1).padStart(2, '0')}`),
      type: String(o.type ?? o.类型 ?? ''),
      question: String(o.question ?? o.问题 ?? ''),
      keywords: String(o.keywords ?? o.判分关键词 ?? ''),
      evidence: String(o.evidence ?? o.证据文件 ?? ''),
    } satisfies EvalQuestion;
  });
}

/* ------------------------------------------------------------ 批量对照 */

export async function startBatch(payload: EvalBatchRequest): Promise<EvalRunSummary> {
  return post<EvalRunSummary>('/eval/batch', payload);
}

export async function fetchBatchRun(id: string): Promise<EvalRun> {
  const raw = (await get<unknown>(`/eval/runs/${encodeURIComponent(id)}`)) ?? {};
  return normalizeRun(raw);
}

export async function listRuns(): Promise<EvalRunSummary[]> {
  const raw = await get<unknown>('/eval/runs');
  const items = Array.isArray(raw) ? raw : ((raw as { items?: unknown[] })?.items ?? []);
  return items.map((item) => normalizeRunSummary(item));
}

function normalizeRunSummary(raw: unknown): EvalRunSummary {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    id: String(o.id ?? ''),
    createdAt: Number(o.createdAt ?? o.created_at ?? Date.now()),
    finishedAt: o.finishedAt ? Number(o.finishedAt) : null,
    status: (['PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED'].includes(String(o.status))
      ? o.status
      : 'RUNNING') as EvalRunSummary['status'],
    progress: Number(o.progress ?? 0),
    stats: (o.stats as EvalRunSummary['stats']) ?? null,
    mode: (o.mode as EvalRunSummary['mode']) ?? 'both',
    k: Number(o.k ?? 3),
  };
}

function normalizeRun(raw: unknown): EvalRun {
  const o = (raw ?? {}) as Record<string, unknown>;
  const base = normalizeRunSummary(o);
  const cases = Array.isArray(o.cases) ? o.cases : [];
  return {
    ...base,
    cases: cases.map((item) => {
      const c = (item ?? {}) as Record<string, unknown>;
      return {
        questionId: String(c.questionId ?? c.question_id ?? ''),
        type: String(c.type ?? ''),
        question: String(c.question ?? ''),
        directAnswer: String(c.directAnswer ?? c.direct_answer ?? ''),
        directPassed: Boolean(c.directPassed ?? c.direct_passed),
        ragAnswer: String(c.ragAnswer ?? c.rag_answer ?? ''),
        ragPassed: Boolean(c.ragPassed ?? c.rag_passed),
        ragSources: Array.isArray(c.ragSources) ? (c.ragSources as string[]) : [],
        elapsedMs: Number(c.elapsedMs ?? c.elapsed_ms ?? 0),
      };
    }),
  };
}

/* ---------------------------------------------------------------- 反馈 */

export async function submitFeedback(messageId: string, payload: FeedbackRequest): Promise<void> {
  await post<void>(`/messages/${encodeURIComponent(messageId)}/feedback`, payload);
}

export async function fetchFeedbackSummary(): Promise<FeedbackSummary> {
  const raw = (await get<unknown>('/feedback/summary')) ?? {};
  const o = raw as Record<string, unknown>;
  return {
    total: Number(o.total ?? 0),
    up: Number(o.up ?? 0),
    down: Number(o.down ?? 0),
    candidates: Number(o.candidates ?? 0),
  };
}

export async function listCandidates(): Promise<EvalCandidate[]> {
  const raw = await get<unknown>('/eval/candidates');
  const items = Array.isArray(raw) ? raw : ((raw as { items?: unknown[] })?.items ?? []);
  return items.map((item) => {
    const o = (item ?? {}) as Record<string, unknown>;
    return {
      id: String(o.id ?? ''),
      question: String(o.question ?? ''),
      source: (o.source === 'manual' ? 'manual' : 'feedback') as EvalCandidate['source'],
      status: (['pending', 'accepted', 'ignored'].includes(String(o.status))
        ? o.status
        : 'pending') as EvalCandidate['status'],
      createdAt: Number(o.createdAt ?? o.created_at ?? Date.now()),
    };
  });
}

export async function decideCandidate(
  id: string,
  status: 'accepted' | 'ignored',
): Promise<void> {
  await post<void>(`/eval/candidates/${encodeURIComponent(id)}/decision`, { status });
}

/* ------------------------------------------------------------ 参数实验 */

export async function createExperiment(payload: {
  name: string;
  axes: ExperimentAxis;
}): Promise<Experiment> {
  return post<Experiment>('/eval/experiments', payload);
}

export async function fetchExperiment(id: string): Promise<Experiment> {
  return get<Experiment>(`/eval/experiments/${encodeURIComponent(id)}`);
}

export async function fetchExperimentReport(id: string): Promise<ExperimentReport> {
  const raw = (await get<unknown>(`/eval/experiments/${encodeURIComponent(id)}/report`)) ?? {};
  const o = raw as Record<string, unknown>;
  const exp = (o.experiment ?? {}) as Record<string, unknown>;
  const runs = Array.isArray(o.runs) ? o.runs : [];
  return {
    experiment: exp as unknown as Experiment,
    runs: runs.map((item) => {
      const r = (item ?? {}) as Record<string, unknown>;
      return {
        id: String(r.id ?? ''),
        params: r.params as ExperimentRun['params'],
        metrics: r.metrics as ExperimentRun['metrics'],
        elapsedMs: Number(r.elapsedMs ?? r.elapsed_ms ?? 0),
      };
    }),
  };
}
