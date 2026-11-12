import type { ChunkItem } from '@/types/api';

/**
 * 片段拼接（F01 查看全文 / 拓展B 重叠观察）。
 *
 * 滑窗分块让相邻片段重叠 overlap 个字，所以「把片段按顺序拼起来」会重复文字。
 * 这里按 start 定位回填，重叠部分只保留一次 —— 得到的就是原文。
 */

export interface MergeResult {
  text: string;
  /** 片段区间之外、无法回填的洞（正常情况下为空） */
  gaps: Array<{ start: number; end: number }>;
}

export function mergeChunks(chunks: ChunkItem[]): MergeResult {
  if (chunks.length === 0) return { text: '', gaps: [] };

  const sorted = [...chunks].sort((a, b) => a.start - b.start || a.end - b.end);
  const total = Math.max(...sorted.map((c) => c.end));
  const buffer: string[] = new Array(total).fill('\u0000');
  const filled = new Array<boolean>(total).fill(false);

  for (const chunk of sorted) {
    const chars = Array.from(chunk.text);
    for (let i = 0; i < chars.length; i += 1) {
      const at = chunk.start + i;
      if (at < 0 || at >= total) continue;
      if (filled[at]) continue;
      buffer[at] = chars[i]!;
      filled[at] = true;
    }
  }

  const gaps: Array<{ start: number; end: number }> = [];
  let runStart = -1;
  for (let i = 0; i < total; i += 1) {
    if (!filled[i]) {
      if (runStart < 0) runStart = i;
    } else if (runStart >= 0) {
      gaps.push({ start: runStart, end: i });
      runStart = -1;
    }
  }
  if (runStart >= 0) gaps.push({ start: runStart, end: total });

  return { text: buffer.join(''), gaps };
}

/** 两份相邻片段的公共前缀长度 —— 用来直观验证 overlap 生效 */
export function overlapLength(a: ChunkItem, b: ChunkItem): number {
  const left = a.text;
  const right = b.text;
  const max = Math.min(left.length, right.length);
  for (let len = max; len > 0; len -= 1) {
    if (left.slice(left.length - len) === right.slice(0, len)) return len;
  }
  return 0;
}

/** 相邻片段对（按 start 排序后 i 与 i+1） */
export function adjacentPairs(chunks: ChunkItem[]): Array<[ChunkItem, ChunkItem]> {
  const sorted = [...chunks].sort((a, b) => a.start - b.start || a.end - b.end);
  const pairs: Array<[ChunkItem, ChunkItem]> = [];
  for (let i = 0; i < sorted.length - 1; i += 1) {
    const a = sorted[i];
    const b = sorted[i + 1];
    if (a && b) pairs.push([a, b]);
  }
  return pairs;
}
