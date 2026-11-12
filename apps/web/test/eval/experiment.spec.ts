import { describe, expect, it } from 'vitest';
import type { ExperimentAxis, ExperimentRun } from '@/types/api';
import {
  AXIS_LABELS,
  countGroups,
  defaultAxes,
  effectiveAxes,
  experimentCsvRows,
  experimentPercent,
  expandAxes,
  formatElapsed,
  formatRate,
  ineffectiveAxes,
  isBestRun,
  paramsLabel,
  pickBestRun,
} from '@/features/eval/composables/experiment';
import { toCsv, csvTimestamp } from '@/utils/csv';

/**
 * 参数矩阵纯函数（套餐 E3）。
 *
 * 三条主线：
 *   ① 笛卡尔积展开正确，且非法组合（overlap >= chunkSize）在展开阶段就被剪掉；
 *   ② 最优行按「命中率 → 耗时 → 来源数」三级排序；
 *   ③ CSV 带 UTF-8 BOM（Excel 打开不乱码）且按 RFC 4180 转义。
 */

function run(id: string, patch: Partial<ExperimentRun['metrics']> = {}, params?: Partial<ExperimentRun['params']>): ExperimentRun {
  return {
    id,
    params: { chunkSize: 180, overlap: 30, k: 3, rerank: true, summary: false, ...params },
    metrics: { hitRate: 0.8, avgElapsedMs: 2000, avgSources: 3, failed: 0, ...patch },
    elapsedMs: 8000,
  };
}

describe('参数矩阵展开（笛卡尔积）', () => {
  it('默认矩阵是单组：180/30 · k=3', () => {
    const axes = defaultAxes();
    expect(axes).toEqual({ chunkSize: [180], overlap: [30], k: [3], rerank: [true], summary: [false] });
    expect(expandAxes(axes)).toEqual([{ chunkSize: 180, overlap: 30, k: 3, rerank: true, summary: false }]);
  });

  it('二维展开顺序稳定：外层 chunkSize、内层 overlap', () => {
    const groups = expandAxes({
      chunkSize: [180, 300],
      overlap: [30],
      k: [3],
      rerank: [true],
      summary: [false],
    });
    expect(groups.map((g) => g.chunkSize)).toEqual([180, 300]);
  });

  it('五维全展开 = 各组数量之积', () => {
    const axes: ExperimentAxis = {
      chunkSize: [180, 300],
      overlap: [30, 50],
      k: [3, 5],
      rerank: [true, false],
      summary: [false, true],
    };
    // 2*2*2*2*2 = 32，但 overlap=50 与 chunkSize=… 均合法（50 < 180 / 300），故全部保留
    expect(expandAxes(axes)).toHaveLength(32);
    expect(countGroups(axes)).toBe(32);
  });

  it('overlap >= chunkSize 的组合被剪掉', () => {
    const groups = expandAxes({
      chunkSize: [180],
      overlap: [30, 180, 200],
      k: [3],
      rerank: [true],
      summary: [false],
    });
    // 只有 30 < 180 合法；180 与 200 都被丢弃
    expect(groups).toHaveLength(1);
    expect(groups[0]?.overlap).toBe(30);
  });

  it('全部组合都非法时返回空数组（UI 据此禁用创建按钮）', () => {
    const groups = expandAxes({
      chunkSize: [50],
      overlap: [50, 100],
      k: [3],
      rerank: [true],
      summary: [false],
    });
    expect(groups).toEqual([]);
    expect(countGroups({
      chunkSize: [50],
      overlap: [50, 100],
      k: [3],
      rerank: [true],
      summary: [false],
    })).toBe(0);
  });
});

describe('最优行挑选', () => {
  it('命中率最高者胜出', () => {
    const best = pickBestRun([run('a', { hitRate: 0.7 }), run('b', { hitRate: 0.95 }), run('c', { hitRate: 0.8 })]);
    expect(best?.id).toBe('b');
  });

  it('命中率相同时取平均耗时更低者', () => {
    const best = pickBestRun([
      run('slow', { hitRate: 0.9, avgElapsedMs: 3000 }),
      run('fast', { hitRate: 0.9, avgElapsedMs: 1200 }),
    ]);
    expect(best?.id).toBe('fast');
  });

  it('命中率与耗时都相同时取来源数更少者（更省 token）', () => {
    const best = pickBestRun([
      run('k5', { hitRate: 0.9, avgElapsedMs: 1500, avgSources: 5 }),
      run('k3', { hitRate: 0.9, avgElapsedMs: 1500, avgSources: 3 }),
    ]);
    expect(best?.id).toBe('k3');
  });

  it('空数组返回 null', () => {
    expect(pickBestRun([])).toBeNull();
  });

  it('isBestRun 按 id 比对，不按参数比对', () => {
    const a = run('g1');
    const b = run('g2'); // 参数完全相同
    const best = pickBestRun([a, b]);
    expect(isBestRun(a, best)).toBe(true);
    expect(isBestRun(b, best)).toBe(false);
    expect(isBestRun(a, null)).toBe(false);
  });

  it('不修改传入数组的顺序', () => {
    const list = [run('a', { hitRate: 0.7 }), run('b', { hitRate: 0.95 })];
    pickBestRun(list);
    expect(list.map((r) => r.id)).toEqual(['a', 'b']);
  });
});

describe('格式化', () => {
  it('命中率保留一位小数', () => {
    expect(formatRate(0.91666)).toBe('91.7%');
    expect(formatRate(1)).toBe('100.0%');
    expect(formatRate(0)).toBe('0.0%');
  });

  it('命中率越界被夹到 0..1', () => {
    expect(formatRate(1.4)).toBe('100.0%');
    expect(formatRate(-0.2)).toBe('0.0%');
  });

  it('耗时转秒', () => {
    expect(formatElapsed(1234)).toBe('1.23s');
    expect(formatElapsed(0)).toBe('0.00s');
    expect(formatElapsed(Number.NaN)).toBe('—');
  });

  it('进度取整并夹到 0..100', () => {
    expect(experimentPercent(33.6)).toBe(34);
    expect(experimentPercent(-5)).toBe(0);
    expect(experimentPercent(180)).toBe(100);
  });

  it('参数标签含分块、k 与两个开关', () => {
    expect(paramsLabel({ chunkSize: 180, overlap: 30, k: 3, rerank: true, summary: false })).toBe(
      '180/30 · k=3 · 重排 · 不摘要',
    );
  });
});

describe('CSV 导出', () => {
  it('toCsv 带 UTF-8 BOM（Excel 打开中文不乱码）', () => {
    const text = toCsv([['题号', '问题'], ['T01', '借几本']]);
    expect(text.startsWith('\uFEFF')).toBe(true);
    expect(text).toBe('\uFEFF题号,问题\r\nT01,借几本');
  });

  it('含逗号的字段整体加引号', () => {
    expect(toCsv([['a,b', 'c']])).toBe('\uFEFF"a,b",c');
  });

  it('内部双引号写成两遍', () => {
    expect(toCsv([['他说"好"']])).toBe('\uFEFF"他说""好"""');
  });

  it('含换行的字段整体加引号，行分隔仍是 CRLF', () => {
    const text = toCsv([['第一行\n第二行'], ['x']]);
    expect(text).toBe('\uFEFF"第一行\n第二行"\r\nx');
  });

  it('null / undefined 落成空字符串', () => {
    expect(toCsv([[null, undefined, 0, false]])).toBe('\uFEFF,,0,false');
  });

  it('实验对比表首行是中文表头，最优行标「是」', () => {
    const runs = [run('g1', { hitRate: 0.7 }), run('g2', { hitRate: 0.95 }, { k: 5 })];
    const rows = experimentCsvRows(runs, pickBestRun(runs));
    expect(rows[0]?.slice(0, 3)).toEqual(['参数组', '片段长度', '重叠']);
    // 13 列：N1 加了「本组生效参数」，N4 加了「未计分题数」。
    expect(rows[0]).toHaveLength(13);
    expect(rows[0]?.[10]).toBe('本组生效参数');
    expect(rows[0]?.[11]).toBe('未计分题数');
    expect(rows[1]?.[12]).toBe('');
    expect(rows[2]?.[12]).toBe('是');
    expect(rows[2]?.[3]).toBe('5');
    expect(rows[2]?.[6]).toBe('95.0%');
  });

  it('生效参数列照抄后端 metrics.effective，未标注时不假装生效', () => {
    const flagged = run('g1', {
      effective: { k: true, rerank: true, chunkSize: true, overlap: true, summary: false },
    });
    const legacy = run('g2');
    const rows = experimentCsvRows([flagged, legacy], null);
    // summary 未生效，不该出现在这一列里。
    expect(rows[1]?.[10]).toBe('k/重排/片段长度/重叠');
    expect(rows[1]?.[10]).not.toContain('摘要');
    // 老报告没有 effective 字段：明说未标注，不要假装全生效。
    expect(rows[2]?.[10]).toBe('（未标注）');
  });

  it('未计分题数原样带出（候选题没填关键词）', () => {
    const rows = experimentCsvRows([run('g1', { unscored: 2 })], null);
    expect(rows[1]?.[11]).toBe('2');
  });

  it('没有最优行时所有行都不标「是」', () => {
    const rows = experimentCsvRows([run('g1')], null);
    expect(rows[1]?.[12]).toBe('');
  });

  it('csvTimestamp 形如 20261030-2315', () => {
    const stamp = csvTimestamp(new Date(2026, 9, 30, 23, 15));
    expect(stamp).toBe('20261030-2315');
  });
});

describe('本组生效参数（N1 的验收核心）', () => {
  it('effective 全 true 时五根轴都算生效', () => {
    const metrics = {
      hitRate: 0.9,
      avgElapsedMs: 1000,
      avgSources: 3,
      failed: 0,
      effective: { k: true, rerank: true, chunkSize: true, overlap: true, summary: true },
    };
    expect(effectiveAxes(metrics)).toEqual(['k', 'rerank', 'chunkSize', 'overlap', 'summary']);
    expect(ineffectiveAxes(metrics)).toEqual([]);
  });

  it('summary=false 时归入未生效，且带中文名', () => {
    const metrics = {
      hitRate: 0.9,
      avgElapsedMs: 1000,
      avgSources: 3,
      failed: 0,
      effective: { k: true, rerank: true, chunkSize: true, overlap: true, summary: false },
    };
    expect(effectiveAxes(metrics)).not.toContain('summary');
    expect(ineffectiveAxes(metrics)).toEqual(['summary']);
    expect(AXIS_LABELS.summary).toBe('摘要');
  });

  it('后端没给 effective 时两个函数都返回空数组（不假装生效）', () => {
    const metrics = { hitRate: 0.9, avgElapsedMs: 1000, avgSources: 3, failed: 0 };
    expect(effectiveAxes(metrics)).toEqual([]);
    expect(ineffectiveAxes(metrics)).toEqual([]);
  });

  it('部分轴缺失时只认显式 true', () => {
    const metrics = {
      hitRate: 0.9,
      avgElapsedMs: 1000,
      avgSources: 3,
      failed: 0,
      effective: { k: true },
    };
    expect(effectiveAxes(metrics)).toEqual(['k']);
    expect(ineffectiveAxes(metrics)).toEqual([]);
  });
});
