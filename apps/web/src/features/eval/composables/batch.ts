import type { EvalCaseResult, EvalQuestion, EvalRun, EvalRunSummary, EvalStats } from '@/types/api';
import { formatDateTime } from '@/utils/time';

/**
 * 批量对照测试的纯函数层（F09）。
 *
 * 判分关键词的规则在 mock 里已实现（`judge()`：`|` 组间全部命中，`/` 组内命中其一），
 * 前端这里**不重算判分**，只做展示层的汇总与格式化 —— 免得前后端两套判分逻辑漂移。
 */

/**
 * 题型中文名：用「用户能看懂的话」描述答案范围，不用行话。
 *
 * - single：答案在一份资料里就能找到；
 * - cross：要综合两份以上资料才能答全；
 * - out：资料库里故意没有答案，考察模型会不会老实说「资料中没有提到」。
 */
export const TYPE_LABELS: Record<string, string> = {
  single: '单份资料可答',
  cross: '需综合多篇',
  out: '库外题（考察拒答）',
};

/** 题型的完整解释：选题目和筛选条上做 hover 提示，一句话讲清这类题考什么 */
export const TYPE_HINTS: Record<string, string> = {
  single: '答案就在一篇上传的资料里，考察「找得到」',
  cross: '答案分散在两份以上资料里，考察「综合归纳」',
  out: '资料库里没有这道题的答案，考察模型会不会老实说「资料中没有提到」而不是瞎编',
};

export function typeHint(type: string): string {
  return TYPE_HINTS[type] ?? '';
}

/** 题型徽标色调：库外题最需要人眼关注，给琥珀 */
export const TYPE_TONES: Record<string, 'info' | 'ok' | 'warn'> = {
  single: 'info',
  cross: 'ok',
  out: 'warn',
};

export function typeLabel(type: string): string {
  // 空串要走兜底：`?? ` 只挡 null/undefined，`''` 会被原样透出成空标签
  return TYPE_LABELS[type] ?? (type || '—');
}

export function typeTone(type: string): 'info' | 'ok' | 'warn' {
  return TYPE_TONES[type] ?? 'info';
}

/**
 * 由用例列表汇总统计。
 *
 * 不直接信后端返回的 `stats`：详情页可能只拿到部分 cases（分页或筛选），
 * 前端按当前可见数据重算，保证「表里几行 = 统计几题」不会自相矛盾。
 */
export function summarize(cases: EvalCaseResult[]): EvalStats {
  return {
    total: cases.length,
    passedDirect: cases.filter((c) => c.directPassed).length,
    passedRag: cases.filter((c) => c.ragPassed).length,
  };
}

/** 通过率百分比（保留一位小数）；分母为 0 时返回 0 */
export function passRate(passed: number, total: number): number {
  if (total <= 0) return 0;
  return Math.round((passed / total) * 1000) / 10;
}

/**
 * 「查资料是否明显更好」的判定。
 *
 * F09 验收第二条要求「查资料通过数明显高于不查资料」。把「明显」量化为
 * **至少多对 2 题**：单题差异可能只是判分关键词碰巧命中，多对 2 题才足以支撑结论。
 * 返回 null 表示两者都跑完了但不构成优势，UI 据此显示中性文案而不是庆祝。
 */
export function ragAdvantage(stats: EvalStats): { better: boolean; diff: number } {
  const diff = stats.passedRag - stats.passedDirect;
  return { better: diff >= 2, diff };
}

/** 结果表 CSV 行（F09「导出 CSV」） */
export function batchCsvRows(cases: EvalCaseResult[]): string[][] {
  const header = [
    '题号',
    '题型',
    '问题',
    '不查资料回答',
    '不查资料初判',
    '查资料回答',
    '查资料初判',
    '来源数',
    '耗时(ms)',
  ];
  const rows = cases.map((c) => [
    c.questionId,
    typeLabel(c.type),
    c.question,
    c.directAnswer,
    c.directPassed ? '通过' : '未通过',
    c.ragAnswer,
    c.ragPassed ? '通过' : '未通过',
    String(c.ragSources.length),
    String(c.elapsedMs),
  ]);
  return [header, ...rows];
}

/**
 * 从题库随机抽 n 道（Fisher-Yates 洗牌后取前 n）。
 *
 * 「想测 N 道」比「逐个勾 N 道」常见得多 —— 抽样跑小批评测是调参时的主路径。
 * n 超过题库总数时返回全部（去重后就是全量），n<=0 返回空。
 */
export function shufflePick(ids: string[], n: number): string[] {
  const size = Math.floor(Math.min(Math.max(n, 0), ids.length));
  const pool = [...ids];
  for (let i = pool.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  return pool.slice(0, size);
}

/** 问题集按题型分组，供「选问题集」时的分组勾选 */
export function groupQuestions(questions: EvalQuestion[]): Array<{ type: string; label: string; items: EvalQuestion[] }> {
  const order = ['single', 'cross', 'out'];
  const buckets = new Map<string, EvalQuestion[]>();
  for (const q of questions) {
    const list = buckets.get(q.type) ?? [];
    list.push(q);
    buckets.set(q.type, list);
  }
  const keys = [...buckets.keys()].sort((a, b) => {
    const ia = order.indexOf(a);
    const ib = order.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  return keys.map((type) => ({ type, label: typeLabel(type), items: buckets.get(type) ?? [] }));
}

/** 运行状态徽标 */
export function runStatusLabel(status: EvalRun['status']): string {
  switch (status) {
    case 'PENDING':
      return '排队中';
    case 'RUNNING':
      return '执行中';
    case 'SUCCEEDED':
      return '已完成';
    case 'FAILED':
      return '失败';
    default:
      return String(status);
  }
}

export function runStatusTone(status: EvalRun['status']): 'ok' | 'warn' | 'error' | 'info' {
  switch (status) {
    case 'SUCCEEDED':
      return 'ok';
    case 'FAILED':
      return 'error';
    case 'RUNNING':
      return 'warn';
    default:
      return 'info';
  }
}

/**
 * 时间戳 → 2026-11-09 14:30
 *
 * A-1 修复：转发到 utils/time 的 formatDateTime（内部做秒/毫秒归一化）。
 * 原先这里直接 new Date(ts)，而后端给的是 Unix 秒，实际显示成 1970-01-22。
 * 导出名保持不变，RunHistory / CandidatePool 的调用点零改动。
 */
export const formatTime = formatDateTime;

/** 回答摘要：表格里塞不下整段，截断到 n 字 */
export function excerpt(text: string, n = 90): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  return flat.length <= n ? flat : `${flat.slice(0, n)}…`;
}

/* ---------------------------------------------------------- 结果筛选与聚合 */

/** 结果表筛选键：all 全部 / failed 只看未通过 / 其余按题型 */
export type FilterKey = 'all' | 'failed' | 'single' | 'cross' | 'out';

/**
 * 按筛选键过滤结果行。
 *
 * 「failed」以**查资料侧未通过**为准：RAG 是产品主链路，rag 挂了就是 badcase，
 * direct 挂而 rag 过的题反而是检索价值的证据，不该混进 badcase 列表。
 */
export function filterCases(cases: EvalCaseResult[], filter: FilterKey): EvalCaseResult[] {
  if (filter === 'all') return cases;
  if (filter === 'failed') return cases.filter((c) => !c.ragPassed);
  return cases.filter((c) => c.type === filter);
}

/** 平均耗时（ms，四舍五入）；空列表返回 0，避免除零 NaN。 */
export function avgElapsed(cases: EvalCaseResult[]): number {
  if (cases.length === 0) return 0;
  return Math.round(cases.reduce((sum, c) => sum + c.elapsedMs, 0) / cases.length);
}

/**
 * 历史趋势点：按时间**正序**取最近 n 次，供 sparkline 画折线。
 *
 * 入参是「新在前」的列表（RunHistory 展示顺序），画趋势必须旧→新，
 * 所以先按 createdAt 升序排，再取末尾 n 个 —— 早期实验数据多了也只看最近几次。
 */
export function trendPoints(
  runs: Array<Pick<EvalRunSummary, 'createdAt' | 'stats'>>,
  n = 10,
): Array<{ ts: number; rate: number }> {
  return [...runs]
    .sort((a, b) => a.createdAt - b.createdAt)
    .filter((r) => (r.stats?.total ?? 0) > 0)
    .slice(-n)
    .map((r) => ({
      ts: r.createdAt,
      rate: passRate(r.stats?.passedRag ?? 0, r.stats?.total ?? 0),
    }));
}
