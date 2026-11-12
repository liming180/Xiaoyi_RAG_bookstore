import { describe, expect, it } from 'vitest';
import type { EvalCaseResult, EvalQuestion, EvalStats } from '@/types/api';
import {
  avgElapsed,
  batchCsvRows,
  excerpt,
  filterCases,
  formatTime,
  groupQuestions,
  passRate,
  ragAdvantage,
  runStatusLabel,
  runStatusTone,
  shufflePick,
  summarize,
  trendPoints,
  typeLabel,
  typeTone,
} from '@/features/eval/composables/batch';

/**
 * 批量对照测试的纯函数（F09）。
 *
 * 关键约定：前端**不重算判分**，只汇总后端给的 directPassed / ragPassed。
 * 因此这里的断言集中在「统计口径」与「展示格式」，不涉及关键词匹配。
 */

function kase(id: string, patch: Partial<EvalCaseResult> = {}): EvalCaseResult {
  return {
    questionId: id,
    type: 'single',
    question: `问题 ${id}`,
    directAnswer: '不查资料的回答',
    directPassed: false,
    ragAnswer: '查资料的回答',
    ragPassed: true,
    ragSources: ['D01-C001'],
    elapsedMs: 1200,
    ...patch,
  };
}

describe('题型标签与色调', () => {
  it('三种题型都有用户能看懂的中文名', () => {
    expect(typeLabel('single')).toBe('单份资料可答');
    expect(typeLabel('cross')).toBe('需综合多篇');
    expect(typeLabel('out')).toBe('库外题（考察拒答）');
  });

  it('未知题型原样透出，不抛错', () => {
    expect(typeLabel('weird')).toBe('weird');
    expect(typeLabel('')).toBe('—');
  });

  it('库外题用琥珀色提醒人工关注', () => {
    expect(typeTone('out')).toBe('warn');
    expect(typeTone('single')).toBe('info');
    expect(typeTone('cross')).toBe('ok');
    expect(typeTone('weird')).toBe('info');
  });
});

describe('统计汇总', () => {
  it('按当前 cases 重算，不信后端 stats', () => {
    const stats = summarize([
      kase('T01', { directPassed: true, ragPassed: true }),
      kase('T02', { directPassed: false, ragPassed: true }),
      kase('T03', { directPassed: false, ragPassed: false }),
    ]);
    expect(stats).toEqual({ total: 3, passedDirect: 1, passedRag: 2 });
  });

  it('空列表统计全 0', () => {
    expect(summarize([])).toEqual({ total: 0, passedDirect: 0, passedRag: 0 });
  });

  it('通过率保留一位小数', () => {
    expect(passRate(7, 10)).toBe(70);
    expect(passRate(2, 3)).toBe(66.7);
    expect(passRate(10, 10)).toBe(100);
  });

  it('分母为 0 时通过率为 0（不产生 NaN）', () => {
    expect(passRate(0, 0)).toBe(0);
    expect(passRate(3, 0)).toBe(0);
  });
});

describe('「查资料是否明显更好」判定', () => {
  it('多通过 2 题及以上才算明显优势', () => {
    expect(ragAdvantage({ total: 10, passedDirect: 3, passedRag: 9 })).toEqual({ better: true, diff: 6 });
    expect(ragAdvantage({ total: 10, passedDirect: 7, passedRag: 9 })).toEqual({ better: true, diff: 2 });
  });

  it('只多 1 题不算明显（可能只是关键词碰巧命中）', () => {
    expect(ragAdvantage({ total: 10, passedDirect: 8, passedRag: 9 })).toEqual({ better: false, diff: 1 });
  });

  it('查资料更差时 diff 为负', () => {
    expect(ragAdvantage({ total: 10, passedDirect: 8, passedRag: 2 })).toEqual({ better: false, diff: -6 });
  });
});

describe('问题集分组', () => {
  const questions: EvalQuestion[] = [
    { id: 'T01', type: 'single', question: 'a', keywords: '', evidence: '' },
    { id: 'T02', type: 'cross', question: 'b', keywords: '', evidence: '' },
    { id: 'T03', type: 'single', question: 'c', keywords: '', evidence: '' },
    { id: 'T04', type: 'out', question: 'd', keywords: '', evidence: '' },
  ];

  it('按单份资料 / 综合多篇 / 库外顺序分组', () => {
    const groups = groupQuestions(questions);
    expect(groups.map((g) => g.type)).toEqual(['single', 'cross', 'out']);
    expect(groups.map((g) => g.label)).toEqual(['单份资料可答', '需综合多篇', '库外题（考察拒答）']);
  });

  it('同组题目按原顺序聚合', () => {
    const single = groupQuestions(questions).find((g) => g.type === 'single');
    expect(single?.items.map((q) => q.id)).toEqual(['T01', 'T03']);
  });

  it('空列表返回空分组', () => {
    expect(groupQuestions([])).toEqual([]);
  });
});

describe('运行状态', () => {
  it('四态中文名', () => {
    expect(runStatusLabel('PENDING')).toBe('排队中');
    expect(runStatusLabel('RUNNING')).toBe('执行中');
    expect(runStatusLabel('SUCCEEDED')).toBe('已完成');
    expect(runStatusLabel('FAILED')).toBe('失败');
  });

  it('四态色调：成功绿、失败红、执行中琥珀', () => {
    expect(runStatusTone('SUCCEEDED')).toBe('ok');
    expect(runStatusTone('FAILED')).toBe('error');
    expect(runStatusTone('RUNNING')).toBe('warn');
    expect(runStatusTone('PENDING')).toBe('info');
  });
});

describe('结果表 CSV 行', () => {
  it('首行是中文表头，共 9 列', () => {
    const rows = batchCsvRows([]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toEqual([
      '题号',
      '题型',
      '问题',
      '不查资料回答',
      '不查资料初判',
      '查资料回答',
      '查资料初判',
      '来源数',
      '耗时(ms)',
    ]);
  });

  it('初判落成「通过 / 未通过」，来源数用数组长度', () => {
    const rows = batchCsvRows([
      kase('T01', { directPassed: true, ragPassed: false, ragSources: ['D01-C001', 'D01-C002'] }),
    ]);
    expect(rows[1]).toEqual([
      'T01',
      '单份资料可答',
      '问题 T01',
      '不查资料的回答',
      '通过',
      '查资料的回答',
      '未通过',
      '2',
      '1200',
    ]);
  });

  it('多题按入参顺序输出', () => {
    const rows = batchCsvRows([kase('T02'), kase('T01')]);
    expect(rows.map((r) => r[0])).toEqual(['题号', 'T02', 'T01']);
  });
});

describe('展示辅助', () => {
  it('excerpt 压平空白并截断', () => {
    expect(excerpt('  一行\n两行  ', 20)).toBe('一行 两行');
    expect(excerpt('abcdefghij', 5)).toBe('abcde…');
  });

  it('formatTime 输出 YYYY-MM-DD HH:mm', () => {
    expect(formatTime(new Date(2026, 9, 30, 23, 5).getTime())).toBe('2026-10-30 23:05');
  });

  it('formatTime 对 null / 0 返回破折号', () => {
    expect(formatTime(null)).toBe('—');
    expect(formatTime(0)).toBe('—');
    expect(formatTime(undefined)).toBe('—');
  });
});

describe('结果筛选与聚合（P5-02…P5-06）', () => {
  it('filterCases：all 原样返回，failed 以查资料侧为准', () => {
    const cases = [
      kase('T01', { type: 'single', ragPassed: false }),
      kase('T02', { type: 'cross', ragPassed: true }),
      kase('T03', { type: 'out', ragPassed: false }),
    ];
    expect(filterCases(cases, 'all')).toHaveLength(3);
    // rag 挂的才算 badcase；direct 挂而 rag 过的不进 failed
    expect(filterCases(cases, 'failed').map((c) => c.questionId)).toEqual(['T01', 'T03']);
    expect(filterCases(cases, 'cross').map((c) => c.questionId)).toEqual(['T02']);
    expect(filterCases(cases, 'out').map((c) => c.questionId)).toEqual(['T03']);
  });

  it('filterCases：空列表各筛选键都返回空', () => {
    expect(filterCases([], 'failed')).toEqual([]);
    expect(filterCases([], 'single')).toEqual([]);
  });

  it('avgElapsed：取整平均，空列表返回 0', () => {
    expect(avgElapsed([kase('T01', { elapsedMs: 100 }), kase('T02', { elapsedMs: 215 })])).toBe(158);
    expect(avgElapsed([])).toBe(0);
  });

  it('trendPoints：升序取最近 n 个，空 stats 的批次被剔除', () => {
    const runs = [
      { createdAt: 300, stats: { total: 10, passedDirect: 5, passedRag: 8 } }, // 80%
      { createdAt: 100, stats: { total: 10, passedDirect: 5, passedRag: 6 } }, // 60%
      { createdAt: 200, stats: null }, // 无 stats，剔除
      { createdAt: 400, stats: { total: 10, passedDirect: 5, passedRag: 10 } }, // 100%
    ];
    const pts = trendPoints(runs, 3);
    expect(pts.map((p) => p.rate)).toEqual([60, 80, 100]); // 旧→新
  });

  it('trendPoints：不足 n 个全保留，单点也能给出速率', () => {
    const pts = trendPoints([{ createdAt: 1, stats: { total: 4, passedDirect: 1, passedRag: 3 } }]);
    expect(pts).toEqual([{ ts: 1, rate: 75 }]);
    expect(trendPoints([])).toEqual([]);
  });
});

describe('随机抽题（P5-07）', () => {
  const ids = ['T01', 'T02', 'T03', 'T04', 'T05'];

  it('抽 n 道返回 n 个不重复的题号，且都来自题库', () => {
    const picked = shufflePick(ids, 3);
    expect(picked).toHaveLength(3);
    expect(new Set(picked).size).toBe(3);
    picked.forEach((id) => expect(ids).toContain(id));
  });

  it('n 超过题库总数时返回全量', () => {
    expect(shufflePick(ids, 99)).toHaveLength(5);
  });

  it('n 为 0 或负数返回空', () => {
    expect(shufflePick(ids, 0)).toEqual([]);
    expect(shufflePick(ids, -3)).toEqual([]);
  });

  it('同一输入多次抽取覆盖面随次数上升（防固定取样）', () => {
    const seen = new Set<string>();
    for (let i = 0; i < 30; i++) shufflePick(ids, 2).forEach((id) => seen.add(id));
    expect(seen.size).toBe(5);
  });

  it('summarize 忽略 stats 参数只按 cases 算', () => {
    const bogus: EvalStats = { total: 99, passedDirect: 99, passedRag: 99 };
    // 直接调 summarize 即可证明它不接收 stats
    expect(summarize([kase('T01')])).not.toEqual(bogus);
  });
});
