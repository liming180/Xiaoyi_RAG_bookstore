/**
 * 渲染层公共类型与工具：把 markdown token 树交给 Vue 递归渲染。
 *
 * 这里刻意不做任何 HTML 拼接 —— 见 utils/markdown.ts 的设计说明。
 */
import type { Inline } from '@/utils/markdown';

/** 渲染层统一的引用点击载荷（SourceRef / InlineRenderer 共用） */
export interface CiteClickPayload {
  ref: number | string;
  chunkId: string | null;
  valid: boolean;
}

/** 内联 token 的稳定 key（同一条消息内保证唯一） */
export function inlineKey(node: Inline, index: number): string {
  return `${node.type}-${index}-${node.value.slice(0, 8)}`;
}
