import type { ExperimentAxis, ExperimentMetrics, ExperimentParams, ExperimentRun } from '@/types/api';
import { CHUNK_SIZE_DEFAULT, OVERLAP_DEFAULT, K_DEFAULT } from '@/constants/app';

/**
 * 参数实验的纯函数层（套餐 E3）。
 *
 * 这里刻意不碰 Vue：矩阵展开、最优行挑选、CSV 行构造都是可穷举验证的纯逻辑，
 * 放在 composable 里既方便单测，也让组件只剩「渲染 + 转发事件」。
 */

/** 默认矩阵：与推荐参数一致，单组即可跑通 */
export function defaultAxes(): ExperimentAxis {
  return {
    chunkSize: [CHUNK_SIZE_DEFAULT],
    overlap: [OVERLAP_DEFAULT],
    k: [K_DEFAULT],
    rerank: [true],
    summary: [false],
  };
}

/**
 * 笛卡尔积展开参数组。
 *
 * `overlap >= chunkSize` 的组合直接丢弃 —— 这类组合在 F02 里本来就是非法的，
 * 与其让后端逐组报错，不如前端在展开阶段就剪掉，矩阵里显示的组数即真实可跑组数。
 */
export function expandAxes(axes: ExperimentAxis): ExperimentParams[] {
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

/** 矩阵总组数（含非法组合被剪掉之后的真实值） */
export function countGroups(axes: ExperimentAxis): number {
  return expandAxes(axes).length;
}

/**
 * 挑出最优行。
 *
 * 排序键：命中率高者优先 → 平均耗时低者优先 → 来源数少者优先（更省 token）。
 * 三级排序是必要的：k=3 与 k=5 常常命中率相同，此时应该推荐更便宜的那组。
 * 空数组返回 null，调用方据此不画高亮。
 */
export function pickBestRun(runs: ExperimentRun[]): ExperimentRun | null {
  if (runs.length === 0) return null;
  const sorted = [...runs].sort((a, b) => {
    if (b.metrics.hitRate !== a.metrics.hitRate) return b.metrics.hitRate - a.metrics.hitRate;
    if (a.metrics.avgElapsedMs !== b.metrics.avgElapsedMs) {
      return a.metrics.avgElapsedMs - b.metrics.avgElapsedMs;
    }
    return a.metrics.avgSources - b.metrics.avgSources;
  });
  return sorted[0] ?? null;
}

/** 某一组参数是否就是最优组（按 id 比对，避免同参数多组时高亮错位） */
export function isBestRun(run: ExperimentRun, best: ExperimentRun | null): boolean {
  return best !== null && best.id === run.id;
}

/** 参数组的可读标签，用于表格首列与 CSV */
export function paramsLabel(params: ExperimentParams): string {
  const flags = [params.rerank ? '重排' : '不重排', params.summary ? '摘要' : '不摘要'];
  return `${params.chunkSize}/${params.overlap} · k=${params.k} · ${flags.join(' · ')}`;
}

/** 命中率百分比文案，保留一位小数（0.9166… → 91.7%） */
export function formatRate(rate: number): string {
  return `${(Math.max(0, Math.min(1, rate)) * 100).toFixed(1)}%`;
}

/** 耗时文案：1234 → 1.23s */
export function formatElapsed(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '—';
  return `${(ms / 1000).toFixed(2)}s`;
}

/** 实验进度百分比（0..100 的整数） */
export function experimentPercent(progress: number): number {
  if (!Number.isFinite(progress)) return 0;
  return Math.max(0, Math.min(100, Math.round(progress)));
}

/**
 * 对比表 CSV 行。
 *
 * 首行表头固定中文，Excel 打开即可读；最后一列「最优」用「是」标注，
 * 让导出的表格脱离页面也能看出结论。
 */
export function experimentCsvRows(runs: ExperimentRun[], best: ExperimentRun | null): string[][] {
  const header = ['参数组', '片段长度', '重叠', 'k', '重排', '摘要', '命中率', '平均耗时(ms)', '平均来源数', '失败数', '最优'];
  const rows = runs.map((run) => {
    const m: ExperimentMetrics = run.metrics;
    return [
      paramsLabel(run.params),
      String(run.params.chunkSize),
      String(run.params.overlap),
      String(run.params.k),
      run.params.rerank ? '开' : '关',
      run.params.summary ? '开' : '关',
      formatRate(m.hitRate),
      String(Math.round(m.avgElapsedMs)),
      String(m.avgSources),
      String(m.failed),
      isBestRun(run, best) ? '是' : '',
    ];
  });
  return [header, ...rows];
}
