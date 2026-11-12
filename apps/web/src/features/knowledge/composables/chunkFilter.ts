import type { ChunkItem, CitationKind } from '@/types/api';

/**
 * 片段浏览的纯逻辑（P4-B，覆盖拓展 B + F05 跳转定位）。
 *
 * 这一层刻意不碰 Vue：过滤、分组、树、相邻对、关键词高亮切片全是纯函数，
 * 这样 vitest 可以直接断言规则本身，不用挂载组件。
 */

/* ------------------------------------------------------------------ 标题路径 */

/**
 * heading_path 可能是三种写法：
 *   "# 借阅规则"
 *   "# 借阅规则 > ## 续借"
 *   "第一章/借阅规则/续借"
 * 统一拆成层级数组，空段丢弃。
 */
export function normalizeHeadingPath(path: string): string[] {
  if (!path) return [];
  return path
    .split(/[>/»]/)
    // 先 trim 再剥 # —— "# A > ## B" 拆出来的第二段是 " ## B"，
    // 不先 trim 的话 ^#+ 匹配不上，层级里就会残留 "## B"。
    .map((part) => part.trim().replace(/^#+\s*/, '').trim())
    .filter((part) => part.length > 0);
}

/** 标题路径的展示文本（末级最具体） */
export function headingLabel(path: string): string {
  const parts = normalizeHeadingPath(path);
  return parts.length > 0 ? parts.join(' / ') : '未标注章节';
}

/* ------------------------------------------------------------------ 文档分组 */

export interface DocGroup {
  docId: string;
  docTitle: string;
  verified: boolean;
  count: number;
  chunks: ChunkItem[];
}

/** 按文档分组（保持片段原有顺序，组按 docId 升序） */
export function buildDocGroups(chunks: ChunkItem[]): DocGroup[] {
  const map = new Map<string, DocGroup>();
  for (const chunk of chunks) {
    const hit = map.get(chunk.docId);
    if (hit) {
      hit.chunks.push(chunk);
      hit.count += 1;
      continue;
    }
    map.set(chunk.docId, {
      docId: chunk.docId,
      docTitle: chunk.docTitle,
      verified: chunk.verified,
      count: 1,
      chunks: [chunk],
    });
  }
  return [...map.values()].sort((a, b) => a.docId.localeCompare(b.docId));
}

/* -------------------------------------------------------------------- 标题树 */

export interface HeadingNode {
  /** 全路径，用作选中键 */
  key: string;
  label: string;
  depth: number;
  count: number;
  children: HeadingNode[];
}

/**
 * 把片段按 heading_path 折成树。
 * 同一全路径累加 count；父节点 count 含所有后代。
 */
export function buildHeadingTree(chunks: ChunkItem[]): HeadingNode[] {
  interface Draft {
    key: string;
    label: string;
    depth: number;
    own: number;
    children: Map<string, Draft>;
  }
  const roots = new Map<string, Draft>();

  for (const chunk of chunks) {
    const parts = normalizeHeadingPath(chunk.headingPath);
    const chain = parts.length > 0 ? parts : ['未标注章节'];
    let level = roots;
    let key = '';
    chain.forEach((label, depth) => {
      key = key ? `${key} > ${label}` : label;
      let node = level.get(key);
      if (!node) {
        node = { key, label, depth, own: 0, children: new Map() };
        level.set(key, node);
      }
      if (depth === chain.length - 1) node.own += 1;
      level = node.children;
    });
  }

  const finalize = (level: Map<string, Draft>): HeadingNode[] =>
    [...level.values()]
      .sort((a, b) => a.label.localeCompare(b.label, 'zh-Hans-CN'))
      .map((node) => {
        const children = finalize(node.children);
        const childTotal = children.reduce((sum, child) => sum + child.count, 0);
        return {
          key: node.key,
          label: node.label,
          depth: node.depth,
          count: node.own + childTotal,
          children,
        };
      });

  return finalize(roots);
}

/* ---------------------------------------------------------------------- 过滤 */

export interface ChunkFilters {
  docId?: string | null;
  /** 标题全路径前缀（选中某个树节点时） */
  heading?: string | null;
  keyword?: string | null;
  kind?: CitationKind | null;
}

/** 判断片段的标题路径是否落在选中节点下（前缀匹配，含自身） */
export function matchesHeading(chunk: ChunkItem, heading: string): boolean {
  const full = normalizeHeadingPath(chunk.headingPath).join(' > ');
  if (!full) return heading === '未标注章节';
  return full === heading || full.startsWith(`${heading} > `);
}

/** 关键词是否命中（大小写不敏感，纯子串） */
export function matchesKeyword(chunk: ChunkItem, keyword: string): boolean {
  const needle = keyword.trim().toLowerCase();
  if (!needle) return true;
  if (chunk.text.toLowerCase().includes(needle)) return true;
  if (chunk.docTitle.toLowerCase().includes(needle)) return true;
  if (chunk.chunkId.toLowerCase().includes(needle)) return true;
  return headingLabel(chunk.headingPath).toLowerCase().includes(needle);
}

export function filterChunks(chunks: ChunkItem[], filters: ChunkFilters = {}): ChunkItem[] {
  const { docId, heading, keyword, kind } = filters;
  return chunks.filter((chunk) => {
    if (docId && chunk.docId !== docId) return false;
    if (kind && chunk.kind !== kind) return false;
    if (heading && !matchesHeading(chunk, heading)) return false;
    if (keyword && !matchesKeyword(chunk, keyword)) return false;
    return true;
  });
}

/* ------------------------------------------------------------------ 定位与相邻 */

/** 按 chunkId 找片段；找不到返回 -1 */
export function indexOfChunk(chunks: ChunkItem[], chunkId: string): number {
  const needle = chunkId.trim().toUpperCase();
  return chunks.findIndex((c) => c.chunkId.toUpperCase() === needle);
}

export interface ChunkNeighborhood {
  prev: ChunkItem | null;
  self: ChunkItem;
  next: ChunkItem | null;
}

/** 同文档内、按 start 排序后的相邻三件套 —— 「相邻片段并排」用它取邻居 */
export function neighborhoodOf(chunks: ChunkItem[], chunkId: string): ChunkNeighborhood | null {
  const needle = chunkId.trim().toUpperCase();
  const self = chunks.find((c) => c.chunkId.toUpperCase() === needle);
  if (!self) return null;
  const siblings = chunks
    .filter((c) => c.docId === self.docId)
    .sort((a, b) => a.start - b.start || a.end - b.end);
  const at = siblings.findIndex((c) => c.chunkId === self.chunkId);
  return {
    prev: at > 0 ? (siblings[at - 1] ?? null) : null,
    self,
    next: at >= 0 ? (siblings[at + 1] ?? null) : null,
  };
}

/* ---------------------------------------------------------------- 高亮切片 */

export interface Slice {
  text: string;
  hit: boolean;
}

/**
 * 关键词高亮切片（大小写不敏感）。
 * 与 utils/text.ts 的 highlightSegments 不同：那个按问题分词，这个按单一关键词。
 */
export function splitHighlight(text: string, keyword: string): Slice[] {
  const needle = keyword.trim();
  if (!text) return [];
  if (!needle) return [{ text, hit: false }];

  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(`(${escaped})`, 'gi');
  const parts = text.split(re);
  return parts
    .filter((part) => part !== '')
    .map((part) => ({ text: part, hit: part.toLowerCase() === needle.toLowerCase() }));
}
