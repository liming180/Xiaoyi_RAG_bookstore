/**
 * 安全 Markdown 渲染器（B3 结构化回答）
 *
 * 设计原则：
 *  1. 绝不使用 v-html —— 检索到的资料里可能夹带 `<img onerror=...>` 这类注入，
 *     任何「先拼字符串再塞 innerHTML」的做法都会执行它。
 *  2. 只解析白名单语法：标题 / 无序列表 / 有序列表 / 表格 / 加粗 / 链接。
 *     其余一律降级为纯文本，HTML 标签当作字面量文本输出（会被 Vue 转义）。
 *  3. 链接只允许 http/https，其它协议（javascript:、data:）降级为纯文本。
 *
 * 输出是结构化 token 树，由 Vue 组件递归渲染，天然免疫 XSS。
 */

export type Inline =
  | { type: 'text'; value: string }
  | { type: 'bold'; value: string }
  | { type: 'link'; value: string; href: string };

export type Block =
  | { type: 'heading'; level: number; inlines: Inline[] }
  | { type: 'list'; ordered: boolean; items: Inline[][] }
  | { type: 'table'; header: Inline[][]; rows: Inline[][][] }
  | { type: 'paragraph'; inlines: Inline[] };

const SAFE_HREF = /^https?:\/\/[^\s]+$/i;

/** 行内解析：**粗体** 与 [文本](http...) */
export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  const re = /\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)/g;
  let last = 0;
  let m = re.exec(text);
  while (m) {
    if (m.index > last) out.push({ type: 'text', value: text.slice(last, m.index) });
    if (m[1] !== undefined) {
      out.push({ type: 'bold', value: m[1] });
    } else if (m[2] !== undefined && m[3] !== undefined) {
      const href = m[3];
      if (SAFE_HREF.test(href)) {
        out.push({ type: 'link', value: m[2], href });
      } else {
        // 危险协议：整段降级成字面文本
        out.push({ type: 'text', value: m[0] });
      }
    }
    last = m.index + m[0].length;
    m = re.exec(text);
  }
  if (last < text.length) out.push({ type: 'text', value: text.slice(last) });
  return out.length > 0 ? out : [{ type: 'text', value: text }];
}

function splitRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  return trimmed.split('|').map((cell) => cell.trim());
}

const TABLE_SEP = /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$/;

export function parseMarkdown(input: string): Block[] {
  const lines = (input ?? '').replace(/\r\n?/g, '\n').split('\n');
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i] ?? '';
    const trimmed = line.trim();

    if (trimmed === '') {
      i += 1;
      continue;
    }

    // 标题
    const heading = /^(#{1,6})\s+(.*)$/.exec(trimmed);
    if (heading) {
      blocks.push({
        type: 'heading',
        level: heading[1]!.length,
        inlines: parseInline(heading[2] ?? ''),
      });
      i += 1;
      continue;
    }

    // 表格：当前行是 |...|，下一行是分隔行
    if (trimmed.startsWith('|') && i + 1 < lines.length && TABLE_SEP.test((lines[i + 1] ?? '').trim())) {
      const header = splitRow(trimmed).map(parseInline);
      i += 2;
      const rows: Inline[][][] = [];
      while (i < lines.length) {
        const row = (lines[i] ?? '').trim();
        if (!row.startsWith('|')) break;
        rows.push(splitRow(row).map(parseInline));
        i += 1;
      }
      blocks.push({ type: 'table', header, rows });
      continue;
    }

    // 列表
    const listItem = /^([-*+]|\d+[.)])\s+(.*)$/.exec(trimmed);
    if (listItem) {
      const ordered = /\d/.test(listItem[1] ?? '');
      const items: Inline[][] = [];
      while (i < lines.length) {
        const cur = (lines[i] ?? '').trim();
        const m = /^([-*+]|\d+[.)])\s+(.*)$/.exec(cur);
        if (!m) break;
        if (/\d/.test(m[1] ?? '') !== ordered) break;
        items.push(parseInline(m[2] ?? ''));
        i += 1;
      }
      blocks.push({ type: 'list', ordered, items });
      continue;
    }

    // 段落：连续非空、非特殊起始的行
    const para: string[] = [];
    while (i < lines.length) {
      const cur = (lines[i] ?? '').trim();
      if (cur === '') break;
      if (/^#{1,6}\s+/.test(cur)) break;
      if (/^([-*+]|\d+[.)])\s+/.test(cur)) break;
      if (cur.startsWith('|')) break;
      para.push(cur);
      i += 1;
    }
    if (para.length > 0) {
      blocks.push({ type: 'paragraph', inlines: parseInline(para.join(' ')) });
    }
  }

  return blocks;
}

/** 从 markdown 里剥离 HTML 标签，用于纯文本兜底（流式阶段） */
export function stripHtml(text: string): string {
  return text.replace(/<\/?[a-z][^>]*>/gi, '');
}
