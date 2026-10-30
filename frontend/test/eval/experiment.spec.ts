import { describe, expect, it } from 'vitest';
import type { ExperimentAxis, ExperimentRun } from '@/types/api';
import {
  countGroups,
  defaultAxes,
  experimentCsvRows,
  experimentPercent,
  expandAxes,
  formatElapsed,
  formatRate,
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
    expect(rows[0]).toHaveLength(11);
    expect(rows[1]?.[10]).toBe('');
    expect(rows[2]?.[10]).toBe('是');
    expect(rows[2]?.[3]).toBe('5');
    expect(rows[2]?.[6]).toBe('95.0%');
  });

  it('没有最优行时所有行都不标「是」', () => {
    const rows = experimentCsvRows([run('g1')], null);
    expect(rows[1]?.[10]).toBe('');
  });

  it('csvTimestamp 形如 20261030-2315', () => {
    const stamp = csvTimestamp(new Date(2026, 9, 30, 23, 15));
    expect(stamp).toBe('20261030-2315');
  });
});
