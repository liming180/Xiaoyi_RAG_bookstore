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
import { get, http, post } from '../http';

/* ---------------------------------------------------------------- 题目 */

/**
 * 题库归一化。
 *
 * <p>P5-08 起题库来自 `eval_question` 表，比种子 CSV 多了 `enabled` 与 `source` 两个字段：
 * 管理界面要靠 `enabled` 显示停用态、靠 `source` 判断能不能删（内置种子题只能停用）。
 */
function normalizeQuestion(item: unknown, i = 0): EvalQuestion {
  const o = (item ?? {}) as Record<string, unknown>;
  return {
    id: String(o.id ?? o.编号 ?? `T${String(i + 1).padStart(2, '0')}`),
    type: String(o.type ?? o.类型 ?? ''),
    question: String(o.question ?? o.问题 ?? ''),
    keywords: String(o.keywords ?? o.判分关键词 ?? ''),
    evidence: String(o.evidence ?? o.证据文件 ?? ''),
    enabled: o.enabled === undefined ? true : Boolean(o.enabled),
    source: String(o.source ?? 'seed'),
  } satisfies EvalQuestion;
}

/** 当前用户**启用中**的题库，评测选题用这条。 */
export async function listQuestions(): Promise<EvalQuestion[]> {
  const raw = await get<unknown>('/eval/questions');
  const items = Array.isArray(raw) ? raw : ((raw as { items?: unknown[] })?.items ?? []);
  return items.map((item, i) => normalizeQuestion(item, i));
}

/** 题库全量（含停用），管理界面用这条。 */
export async function listAllQuestions(): Promise<EvalQuestion[]> {
  const raw = await get<unknown>('/eval/questions/all');
  const items = Array.isArray(raw) ? raw : ((raw as { items?: unknown[] })?.items ?? []);
  return items.map((item, i) => normalizeQuestion(item, i));
}

/** 新增题目；code 留空时后端按题型自动编号（S001 / X001 / O001）。 */
export async function createQuestion(payload: {
  code?: string;
  type: string;
  question: string;
  keywords?: string;
  evidence?: string;
}): Promise<EvalQuestion> {
  return normalizeQuestion(await post<unknown>('/eval/questions', payload));
}

/** 修改题目；题号不可改（已被历史评测快照引用）。 */
export async function updateQuestion(
  code: string,
  payload: { type: string; question: string; keywords?: string; evidence?: string },
): Promise<EvalQuestion> {
  const raw = await http.put<unknown>(
    `/eval/questions/${encodeURIComponent(code)}`,
    payload,
  );
  return normalizeQuestion(raw.data);
}

/** 停用 / 启用题目。停用后不再进入新评测，但历史评测照常可读。 */
export async function setQuestionEnabled(code: string, enabled: boolean): Promise<EvalQuestion> {
  const raw = await post<unknown>(`/eval/questions/${encodeURIComponent(code)}/enabled`, {
    enabled,
  });
  return normalizeQuestion(raw);
}

/** 删除题目；内置种子题会被后端拒绝（只能停用）。 */
export async function deleteQuestion(code: string): Promise<void> {
  await http.delete<void>(`/eval/questions/${encodeURIComponent(code)}`);
}

/** 导出题库 CSV（列与 questions.csv 对齐，可直接再导入）。 */
export async function exportQuestions(): Promise<Blob> {
  const response = await http.get<Blob>('/eval/questions/export', { responseType: 'blob' });
  return response.data;
}

/** 从 CSV 导入题目；题号冲突跳过并计数，不整批失败。 */
export async function importQuestions(csv: string): Promise<{
  created: number;
  skipped: number;
  errors: string[];
}> {
  const raw = await post<unknown>('/eval/questions/import', { csv });
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    created: Number(o.created ?? 0),
    skipped: Number(o.skipped ?? 0),
    errors: Array.isArray(o.errors) ? (o.errors as string[]) : [],
  };
}

/* ------------------------------------------------------------ 批量对照 */

/**
 * 发起批量评测。
 *
 * <p>选题有两条路径：`questionIds` 非空 = 精确点选；为空则按 `types` / `sample` / `limit` 由服务端筛选。
 * 筛选必须在服务端做 —— 题库是用户数据会持续增长，前端每次先拉全库再回传题号既慢又容易不一致。
 */
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
  keywords?: string,
): Promise<void> {
  const body: { status: string; keywords?: string } = { status };
  // 只有 accepted 才带关键词：ignored 的候选不会进实验，写了也没人读。
  if (status === 'accepted' && keywords !== undefined && keywords.trim() !== '') {
    body.keywords = keywords.trim();
  }
  await post<void>(`/eval/candidates/${encodeURIComponent(id)}/decision`, body);
}

/**
 * 导出已采纳候选为题库 CSV（`question,keywords` 两列，带 BOM）。
 *
 * 必须走 `responseType: 'blob'`：这条端点返回 `text/csv`，默认 JSON 解析会先炸掉。
 * 响应拦截器对 Blob 不做 Result 拆包（`'code' in blob` 为 false），原样返回，正好。
 */
export async function exportCandidates(): Promise<Blob> {
  const response = await http.get<Blob>('/eval/candidates/export', { responseType: 'blob' });
  return response.data;
}

/* ------------------------------------------------------------ 参数实验 */

export async function createExperiment(payload: {
  name: string;
  /** 选题：空 = 全 13 道题库题；`T01`–`T13` 走题库，`C<候选id>` 走候选池 */
  questionIds?: string[];
  axes: ExperimentAxis;
}): Promise<Experiment> {
  const body: { name: string; axes: ExperimentAxis; questionIds?: string[] } = {
    name: payload.name,
    axes: payload.axes,
  };
  if (payload.questionIds && payload.questionIds.length > 0) {
    body.questionIds = payload.questionIds;
  }
  return post<Experiment>('/eval/experiments', body);
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
