import type { Citation } from '@/types/api';

/**
 * 回答正文里的引用编号解析。
 *
 * 支持两种写法：
 *   [1]         → 编号引用（对应 citations[].ref === 1）
 *   [D02-C001]  → 片段 ID 引用（对应 citations[].chunkId === 'D02-C001'）
 *
 * 关键约束：编号必须在 citations 里真实存在才算「有效引用」，
 * 否则渲染成灰色不可点（幻觉引用），绝不允许点开空卡片。
 */

export type AnswerNode =
  | { type: 'text'; value: string }
  | { type: 'cite'; raw: string; ref: number | string; chunkId: string | null; valid: boolean };

const CITE_RE = /\[(\d{1,2})\]|\[([Dd]\d{2}-[Cc]\d{3})\]/g;

export function answerNodes(text: string, citations: Citation[] = []): AnswerNode[] {
  const nodes: AnswerNode[] = [];
  if (!text) return nodes;

  const byRef = new Map<string, Citation>();
  const byChunk = new Map<string, Citation>();
  for (const c of citations) {
    byRef.set(String(c.ref), c);
    if (c.chunkId) byChunk.set(c.chunkId.toUpperCase(), c);
  }

  let last = 0;
  CITE_RE.lastIndex = 0;
  let match = CITE_RE.exec(text);
  while (match) {
    if (match.index > last) {
      nodes.push({ type: 'text', value: text.slice(last, match.index) });
    }
    const numeric = match[1];
    const chunkish = match[2];
    if (numeric !== undefined) {
      const hit = byRef.get(numeric);
      nodes.push({
        type: 'cite',
        raw: match[0],
        ref: Number(numeric),
        chunkId: hit?.chunkId ?? null,
        valid: Boolean(hit),
      });
    } else if (chunkish !== undefined) {
      const hit = byChunk.get(chunkish.toUpperCase());
      nodes.push({
        type: 'cite',
        raw: match[0],
        ref: hit?.ref ?? chunkish,
        chunkId: chunkish.toUpperCase(),
        valid: Boolean(hit),
      });
    }
    last = match.index + match[0].length;
    match = CITE_RE.exec(text);
  }
  if (last < text.length) nodes.push({ type: 'text', value: text.slice(last) });
  return nodes;
}

/** 「第 1 字至第 180 字」（与后端旧实现口径一致：start 从 0 起，展示 +1） */
export function positionText(start: number, end: number): string {
  return `第 ${start + 1} 字至第 ${end} 字`;
}

/** 得分条宽度，最小 4% 保证可见 */
export function scoreWidth(score: number): string {
  const pct = Math.max(4, Math.min(100, Math.round(score * 100)));
  return `${pct}%`;
}

/** 关键词高亮切分（用于摘录里标命中词） */
export interface HighlightSegment {
  text: string;
  hit: boolean;
}

export function highlightTokens(question: string): string[] {
  if (!question) return [];
  // 用 \u005B / \u005D 表示方括号，避免字符类里的转义歧义
  const PUNCT_RE = /[，。？！、；：“”‘’（）()《》\u005B\u005D{}<>:;,.?!"'`~@#$%^&*+=|\\/_—\-\s]/g;
  const cleaned = question.replace(PUNCT_RE, ' ');
  const tokens = cleaned
    .split(' ')
    .map((t) => t.trim())
    .filter((t) => t.length >= 2);
  return Array.from(new Set(tokens)).slice(0, 6);
}

export function highlightSegments(text: string, question: string): HighlightSegment[] {
  const tokens = highlightTokens(question);
  if (tokens.length === 0 || !text) return [{ text, hit: false }];

  const escaped = tokens.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const re = new RegExp(`(${escaped.join('|')})`, 'g');
  const parts = text.split(re);
  return parts
    .filter((p) => p !== '')
    .map((p) => ({ text: p, hit: tokens.includes(p) }));
}

/** 截断长文本（保留首尾语义，中间省略） */
export function truncate(text: string, max = 160): string {
  if (!text) return '';
  const flat = text.replace(/\s+/g, ' ').trim();
  return flat.length <= max ? flat : `${flat.slice(0, max)}…`;
}

/**
 * 在 citations 里按编号或片段 ID 找引用（F05）。
 *
 * 找不到即「幻觉引用」：渲染层必须置灰不可点，绝不允许点开空卡片。
 */
export function resolveCitation(
  citations: Citation[],
  ref: number | string,
  chunkId: string | null,
): Citation | null {
  for (const c of citations) {
    if (String(c.ref) === String(ref)) return c;
    if (chunkId && c.chunkId && c.chunkId.toUpperCase() === chunkId.toUpperCase()) return c;
  }
  return null;
}

/** 引用徽标上显示的文本：数字引用显示 [1]，片段 ID 引用显示片段号 C001 */
export function citeLabel(ref: number | string, chunkId: string | null): string {
  if (typeof ref === 'number') return String(ref);
  const hit = chunkId ?? String(ref);
  const m = /-C(\d{3})$/i.exec(hit);
  return m ? m[1]!.replace(/^0+/, '') || '0' : hit;
}
