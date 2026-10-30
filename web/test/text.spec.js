import { describe, expect, it } from 'vitest';
import { answerNodes, highlightSegments, highlightTokens, positionText, scoreWidth } from '../src/utils/text.js';

describe('answerNodes', () => {
  const citations = [
    { ref: 1, chunk_id: 'D02-C001' },
    { ref: 2, chunk_id: 'D01-C001' },
  ];

  it('把有效编号渲染成可点击节点，ref 与 chunk_id 两种写法都能命中', () => {
    const nodes = answerNodes('最多借阅4本。[1] 另外见 [D01-C001]。', citations);
    const cites = nodes.filter((n) => n.type === 'cite');
    expect(cites).toHaveLength(2);
    expect(cites[0].chunk_id).toBe('D02-C001');
    expect(cites[0].raw).toBe('[1]');
    expect(cites[1].chunk_id).toBe('D01-C001');
  });

  it('无效编号原样当文本，不造假来源', () => {
    const nodes = answerNodes('结论 [9] 到此。', citations);
    expect(nodes.filter((n) => n.type === 'cite')).toHaveLength(0);
    expect(nodes.map((n) => n.value || n.raw).join('')).toBe('结论 [9] 到此。');
  });

  it('无编号时返回单个文本节点', () => {
    const nodes = answerNodes('资料中没有提供联系电话。', citations);
    expect(nodes).toEqual([{ type: 'text', value: '资料中没有提供联系电话。' }]);
  });

  it('空输入不报错', () => {
    expect(answerNodes('', citations)).toEqual([]);
    expect(answerNodes(null, citations)).toEqual([]);
  });
});

describe('highlightTokens / highlightSegments', () => {
  it('按标点切词，保留 2 字以上，最多 6 个', () => {
    expect(highlightTokens('讨论空间需要几人每次最长多久？')).toEqual(['讨论空间需要几人每次最长多久']);
    expect(highlightTokens('续借，规则？')).toEqual(['续借', '规则']);
    expect(highlightTokens('a b c')).toEqual([]);
  });

  it('命中词渲染成 hit 片段，其余为普通片段', () => {
    const segs = highlightSegments('被预约的图书不能续借。', '续借');
    expect(segs.map((s) => s.text).join('')).toBe('被预约的图书不能续借。');
    expect(segs.filter((s) => s.hit).map((s) => s.text)).toEqual(['续借']);
  });

  it('多关键词重叠区间合并，不产生嵌套 mark', () => {
    const segs = highlightSegments('讨论空间供3至6人使用', '讨论空间 空间供3');
    const hits = segs.filter((s) => s.hit).map((s) => s.text);
    expect(hits).toEqual(['讨论空间供3']);
    expect(segs.every((s) => typeof s.text === 'string')).toBe(true);
  });

  it('无关键词时整段普通返回', () => {
    expect(highlightSegments('正文', '')).toEqual([{ text: '正文', hit: false }]);
  });
});

describe('positionText / scoreWidth', () => {
  it('位置从 1 开始计', () => {
    expect(positionText({ start: 0, end: 180 })).toBe('第 1–180 字');
    expect(positionText({ start: 150, end: 294 })).toBe('第 151–294 字');
  });

  it('得分条最小 4%', () => {
    expect(scoreWidth(0)).toBe('4%');
    expect(scoreWidth(0.8342)).toBe('83%');
    expect(scoreWidth(null)).toBe('4%');
  });
});
