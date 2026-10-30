import { describe, expect, it } from 'vitest';
import { parseInline, parseMarkdown } from '@/utils/markdown';
import { answerNodes, citeLabel, positionText, resolveCitation } from '@/utils/text';
import type { Citation } from '@/types/api';

function makeCitation(over: Partial<Citation> = {}): Citation {
  return {
    ref: 1,
    chunkId: 'D02-C001',
    docId: 'D02',
    docTitle: '02_借阅规则.md',
    headingPath: '借阅数量',
    text: '已登记成员每人最多同时借阅 4 本普通图书，每本借期 21 天。',
    start: 0,
    end: 30,
    score: 0.87,
    kind: 'chunk',
    verified: true,
    ...over,
  };
}

describe('引用编号解析（F05）', () => {
  it('answerNodes 把 [1] 切成 cite 节点，并标出有效性', () => {
    const nodes = answerNodes('最多借 4 本 [1]，续借 7 天 [2]。', [makeCitation()]);
    const cites = nodes.filter((n) => n.type === 'cite');
    expect(cites).toHaveLength(2);
    expect(cites[0]).toMatchObject({ ref: 1, chunkId: 'D02-C001', valid: true });
    // [2] 不在 citations 里 → 幻觉引用
    expect(cites[1]).toMatchObject({ ref: 2, valid: false });
  });

  it('parseInline 能识别片段 ID 形式 [D02-C001]', () => {
    const inlines = parseInline('见 [D02-C001] 原文。');
    const cite = inlines.find((n) => n.type === 'cite');
    expect(cite).toMatchObject({ type: 'cite', chunkId: 'D02-C001' });
  });

  it('表格单元格里的编号也能被解析出来', () => {
    const md = ['| 项目 | 规则 |', '| --- | --- |', '| 同时借阅上限 | 4 本 [1] |'].join('\n');
    const blocks = parseMarkdown(md);
    expect(blocks).toHaveLength(1);
    const table = blocks[0];
    expect(table?.type).toBe('table');
    if (table?.type !== 'table') throw new Error('应解析为表格');
    const cells = table.rows[0] ?? [];
    const flat = cells.flat();
    expect(flat.some((n) => n.type === 'cite')).toBe(true);
  });

  it('markdown 链接不会被误判成引用编号', () => {
    const inlines = parseInline('[文档](https://example.com/a)');
    expect(inlines).toHaveLength(1);
    expect(inlines[0]).toMatchObject({ type: 'link', href: 'https://example.com/a' });
  });

  it('危险协议链接降级成字面文本', () => {
    const inlines = parseInline('[点我](javascript:alert(1))');
    expect(inlines.some((n) => n.type === 'link')).toBe(false);
    expect(inlines.map((n) => n.value).join('')).toContain('javascript:alert(1)');
  });

  it('resolveCitation 同时支持编号与片段 ID 两种匹配', () => {
    const list = [makeCitation()];
    expect(resolveCitation(list, 1, null)?.chunkId).toBe('D02-C001');
    expect(resolveCitation(list, 'D02-C001', 'D02-C001')?.ref).toBe(1);
    expect(resolveCitation(list, 9, null)).toBeNull();
  });

  it('citeLabel 把片段 ID 简写成 C001 的数字部分', () => {
    expect(citeLabel(3, null)).toBe('3');
    expect(citeLabel('D02-C001', 'D02-C001')).toBe('1');
  });

  it('positionText 输出「第 N 字至第 M 字」', () => {
    expect(positionText(0, 180)).toBe('第 1 字至第 180 字');
  });
});

describe('XSS 防护（B3 白名单）', () => {
  it('img onerror 不会被解析成标签，只作为纯文本 token', () => {
    const md = '正常文字 <img src=x onerror="alert(1)"> 后续文字';
    const blocks = parseMarkdown(md);
    expect(blocks).toHaveLength(1);
    const p = blocks[0];
    if (p?.type !== 'paragraph') throw new Error('应解析为段落');
    const text = p.inlines.map((n) => ('value' in n ? n.value : '')).join('');
    // 标签原样保留为文本，由 Vue 转义后显示
    expect(text).toContain('<img');
    expect(p.inlines.every((n) => n.type === 'text')).toBe(true);
  });

  it('script 标签同样只当文本', () => {
    const blocks = parseMarkdown('<script>alert(1)</script>');
    const p = blocks[0];
    if (p?.type !== 'paragraph') throw new Error('应解析为段落');
    expect(p.inlines.every((n) => n.type === 'text')).toBe(true);
  });
});
