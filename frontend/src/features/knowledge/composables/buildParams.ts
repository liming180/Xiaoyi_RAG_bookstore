import {
  CHUNK_SIZE_DEFAULT,
  CHUNK_SIZE_MAX,
  CHUNK_SIZE_MIN,
  INDEX_STAGE_LABELS,
  OVERLAP_DEFAULT,
} from '@/constants/app';
import type { IndexTask } from '@/types/api';

/**
 * 分块参数的纯函数规则层（F02）。
 *
 * 抽成纯函数的原因：校验规则是「前端先挡一层」的硬约束，
 * 用 vitest 直接断言比通过组件点按钮可靠得多。
 */

export interface BuildParams {
  chunkSize: number;
  overlap: number;
}

/** 默认 180 / 30 —— 取自 F02 功能规格与项目实际建库结果（15 个片段） */
export const DEFAULT_BUILD_PARAMS: BuildParams = {
  chunkSize: CHUNK_SIZE_DEFAULT,
  overlap: OVERLAP_DEFAULT,
};

/** 合法返回 null，不合法返回给用户看的中文原因 */
export function validateBuildParams(params: BuildParams): string | null {
  const { chunkSize, overlap } = params;

  if (!Number.isFinite(chunkSize) || !Number.isInteger(chunkSize)) {
    return '片段长度需为整数';
  }
  if (!Number.isFinite(overlap) || !Number.isInteger(overlap)) {
    return '重叠字数需为整数';
  }
  if (chunkSize < CHUNK_SIZE_MIN || chunkSize > CHUNK_SIZE_MAX) {
    return `片段长度需在 ${CHUNK_SIZE_MIN}–${CHUNK_SIZE_MAX} 之间`;
  }
  if (overlap < 0) {
    return '重叠字数需大于等于 0';
  }
  if (overlap >= chunkSize) {
    return '重叠字数需小于片段长度';
  }
  return null;
}

/** 参数与「已建库参数」不一致 → 需要提示重建（F03 联动） */
export function isParamsDirty(
  current: BuildParams,
  built: { chunkSize: number; overlap: number } | null,
): boolean {
  if (!built) return false;
  return current.chunkSize !== built.chunkSize || current.overlap !== built.overlap;
}

/** 进度条百分比：夹到 0..100，终态直接 100 */
export function progressPercent(task: IndexTask | null): number {
  if (!task) return 0;
  if (task.status === 'SUCCEEDED') return 100;
  const value = Number.isFinite(task.progress) ? task.progress : 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

/** 阶段文案：解析资料 / 切分片段 / 生成向量 / 生成摘要 / 完成 */
export function stageLabel(task: IndexTask | null): string {
  if (!task) return '';
  return INDEX_STAGE_LABELS[task.stage] ?? task.stage;
}

/** 完成后的摘要「文档 N 份，片段 M 条」 */
export function formatBuildSummary(task: IndexTask | null): string | null {
  if (!task || task.status !== 'SUCCEEDED') return null;
  return `文档 ${task.docCount} 份，片段 ${task.chunkCount} 条`;
}

/** 终态判定：轮询见到它就停表 */
export function isTerminal(task: IndexTask | null): boolean {
  return task?.status === 'SUCCEEDED' || task?.status === 'FAILED';
}
