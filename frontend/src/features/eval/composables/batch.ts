import type { EvalCaseResult, EvalQuestion, EvalRun, EvalStats } from '@/types/api';

/**
 * 批量对照测试的纯函数层（F09）。
 *
 * 判分关键词的规则在 mock 里已实现（`judge()`：`|` 组间全部命中，`/` 组内命中其一），
 * 前端这里**不重算判分**，只做展示层的汇总与格式化 —— 免得前后端两套判分逻辑漂移。
 */

/** 题型中文名：单文档 / 跨文档 / 库外 */
export const TYPE_LABELS: Record<string, string> = {
  single: '单文档',
  cross: '跨文档',
  out: '库外',
};

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

/** 时间戳 → 2026-10-30 23:15 */
export function formatTime(ts: number | null | undefined): string {
  if (!ts) return '—';
  const d = new Date(ts);
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 回答摘要：表格里塞不下整段，截断到 n 字 */
export function excerpt(text: string, n = 90): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  return flat.length <= n ? flat : `${flat.slice(0, n)}…`;
}
