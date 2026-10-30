/**
 * 文本处理工具 —— 取代旧版 web/legacy/app.js:50 linkCitations 与 :65 highlight 的字符串拼 HTML。
 *
 * 为什么要改成「返回节点数组」而不是返回 HTML 字符串：
 *   - 旧版把用户问题、资料原文、模型回答统统 esc() 后拼进 innerHTML，一旦 esc 漏掉一处就是 XSS；
 *   - Vue 侧用 v-html 会重新引入同一个风险；
 *   - 所以这里只输出结构化节点，模板里 v-for 渲染，浏览器永远把内容当文本。
 * 语义保持完全一致：
 *   - 有效编号 [1] / [D02-C001] → 可点击徽标；
 *   - 无效编号（如模型幻觉出来的 [9]）→ 原样当文本，界面不造假来源。
 */

const CITE_RE = /\[(\d+)\]|\[(D\d{2}-C\d{3})\]/g;

/** 把回答文本切成 [{type:'text'|'cite', ...}] 节点序列 */
export function answerNodes(text, citations = []) {
  const source = String(text == null ? '' : text);
  const byRef = new Map();
  citations.forEach((card) => {
    byRef.set(String(card.ref), card.chunk_id);
    byRef.set(card.chunk_id, card.chunk_id);
  });

  const nodes = [];
  let last = 0;
  CITE_RE.lastIndex = 0;
  let match = CITE_RE.exec(source);
  while (match !== null) {
    if (match.index > last) {
      nodes.push({ type: 'text', value: source.slice(last, match.index) });
    }
    const key = String(match[1] || match[2]);
    const chunkId = byRef.get(key);
    if (chunkId) {
      nodes.push({ type: 'cite', raw: match[0], chunk_id: chunkId });
    } else {
      nodes.push({ type: 'text', value: match[0] });
    }
    last = match.index + match[0].length;
    match = CITE_RE.exec(source);
  }
  if (last < source.length) {
    nodes.push({ type: 'text', value: source.slice(last) });
  }
  return nodes;
}

/** 取出用于高亮的关键词：按标点/空白切分，保留 2 字以上，最多 6 个 */
export function highlightTokens(question) {
  return String(question || '')
    .replace(/[？?。，,、；;：:！!（）()\s]/g, ' ')
    .split(' ')
    .filter((token) => token.length >= 2)
    .slice(0, 6);
}

/**
 * 把片段正文切成 [{text, hit}] —— hit=true 的部分模板里渲染成 <mark>。
 * 多个关键词时按出现顺序扫描，避免旧版「先替换 A 再替换 B 把 A 的 mark 包进 B」的嵌套问题。
 */
export function highlightSegments(text, question) {
  const source = String(text == null ? '' : text);
  const tokens = highlightTokens(question);
  if (!tokens.length) return [{ text: source, hit: false }];

  const hits = [];
  tokens.forEach((token) => {
    let from = 0;
    let at = source.indexOf(token, from);
    while (at !== -1) {
      hits.push([at, at + token.length]);
      from = at + token.length;
      at = source.indexOf(token, from);
    }
  });
  if (!hits.length) return [{ text: source, hit: false }];

  hits.sort((a, b) => a[0] - b[0] || b[1] - a[1]);
  const merged = [];
  hits.forEach(([start, end]) => {
    const tail = merged[merged.length - 1];
    if (tail && start <= tail[1]) {
      tail[1] = Math.max(tail[1], end);
    } else {
      merged.push([start, end]);
    }
  });

  const segments = [];
  let cursor = 0;
  merged.forEach(([start, end]) => {
    if (start > cursor) segments.push({ text: source.slice(cursor, start), hit: false });
    segments.push({ text: source.slice(start, end), hit: true });
    cursor = end;
  });
  if (cursor < source.length) segments.push({ text: source.slice(cursor), hit: false });
  return segments;
}

/** 片段原文位置文案，与后端 /api/chunks 的 position 字段一致 */
export function positionText(chunk) {
  return `第 ${chunk.start + 1}–${chunk.end} 字`;
}

/** 得分条宽度：最小 4%，避免 0 分时看不见 */
export function scoreWidth(score) {
  return `${Math.max(4, Math.round(Number(score || 0) * 100))}%`;
}
