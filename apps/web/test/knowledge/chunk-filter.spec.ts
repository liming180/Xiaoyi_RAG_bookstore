import { describe, expect, it } from 'vitest';
import type { ChunkItem } from '@/types/api';
import {
  buildDocGroups,
  buildHeadingTree,
  filterChunks,
  headingLabel,
  indexOfChunk,
  matchesHeading,
  matchesKeyword,
  neighborhoodOf,
  normalizeHeadingPath,
  splitHighlight,
} from '@/features/knowledge/composables/chunkFilter';
import { mergeChunks, overlapLength, adjacentPairs } from '@/features/knowledge/composables/chunkMerge';

/**
 * 片段浏览纯逻辑（P4-B 拓展 B）。
 *
 * 这一层不碰 Vue，全部是可直接断言的规则：
 * 分组 / 标题树 / 前缀匹配 / 关键词 / 定位 / 相邻 / 重叠字数 / 高亮切片。
 */

function chunk(over: Partial<ChunkItem> & Pick<ChunkItem, 'chunkId' | 'text'>): ChunkItem {
  return {
    docId: 'D01',
    docTitle: '01_活动说明.md',
    headingPath: '# 活动说明',
    start: 0,
    end: over.text.length,
    kind: 'chunk',
    verified: true,
    index: 0,
    ...over,
  };
}

describe('标题路径归一（heading_path 三种写法）', () => {
  it('单级 # 标题', () => {
    expect(normalizeHeadingPath('# 借阅规则')).toEqual(['借阅规则']);
    expect(headingLabel('# 借阅规则')).toBe('借阅规则');
  });

  it('多级 # 用 > 拼接', () => {
    expect(normalizeHeadingPath('# 借阅规则 > ## 续借')).toEqual(['借阅规则', '续借']);
    expect(headingLabel('# 借阅规则 > ## 续借')).toBe('借阅规则 / 续借');
  });

  it('斜杠分隔也认', () => {
    expect(normalizeHeadingPath('第一章/借阅规则/续借')).toEqual(['第一章', '借阅规则', '续借']);
  });

  it('空路径与空段被丢弃', () => {
    expect(normalizeHeadingPath('')).toEqual([]);
    expect(normalizeHeadingPath('# > ## ')).toEqual([]);
    expect(headingLabel('')).toBe('未标注章节');
  });
});

describe('按文档分组', () => {
  const items = [
    chunk({ chunkId: 'D02-C001', docId: 'D02', docTitle: '02_借阅规则.md', text: 'a' }),
    chunk({ chunkId: 'D01-C001', docId: 'D01', text: 'b' }),
    chunk({ chunkId: 'D02-C002', docId: 'D02', docTitle: '02_借阅规则.md', text: 'c' }),
  ];

  it('同文档合并、计数正确、按 docId 升序', () => {
    const groups = buildDocGroups(items);
    expect(groups.map((g) => g.docId)).toEqual(['D01', 'D02']);
    expect(groups[1]?.count).toBe(2);
    expect(groups[1]?.chunks.map((c) => c.chunkId)).toEqual(['D02-C001', 'D02-C002']);
  });

  it('空输入返回空数组', () => {
    expect(buildDocGroups([])).toEqual([]);
  });

  it('未核实文档的 verified 透传到分组', () => {
    const groups = buildDocGroups([
      chunk({ chunkId: 'D06-C001', docId: 'D06', docTitle: '06_成员留言摘录.md', text: 'x', verified: false }),
    ]);
    expect(groups[0]?.verified).toBe(false);
  });
});

describe('标题树', () => {
  const items = [
    chunk({ chunkId: 'A', text: 'a', headingPath: '# 借阅规则' }),
    chunk({ chunkId: 'B', text: 'b', headingPath: '# 借阅规则 > ## 续借' }),
    chunk({ chunkId: 'C', text: 'c', headingPath: '# 借阅规则 > ## 续借' }),
    chunk({ chunkId: 'D', text: 'd', headingPath: '# 空间预约' }),
  ];

  it('父节点计数含子节点', () => {
    const tree = buildHeadingTree(items);
    const borrow = tree.find((n) => n.label === '借阅规则');
    expect(borrow?.count).toBe(3);
    expect(borrow?.children[0]?.label).toBe('续借');
    expect(borrow?.children[0]?.count).toBe(2);
    expect(borrow?.children[0]?.depth).toBe(1);
  });

  it('顶层按中文排序，根节点 depth=0', () => {
    const tree = buildHeadingTree(items);
    expect(tree.map((n) => n.label)).toEqual(['借阅规则', '空间预约']);
    expect(tree[0]?.depth).toBe(0);
    expect(tree[0]?.key).toBe('借阅规则');
    expect(tree[0]?.children[0]?.key).toBe('借阅规则 > 续借');
  });

  it('空 heading_path 归入「未标注章节」', () => {
    const tree = buildHeadingTree([chunk({ chunkId: 'E', text: 'e', headingPath: '' })]);
    expect(tree.map((n) => n.label)).toEqual(['未标注章节']);
  });

  it('空输入返回空树', () => {
    expect(buildHeadingTree([])).toEqual([]);
  });
});

describe('标题前缀匹配', () => {
  const parent = chunk({ chunkId: 'A', text: 'a', headingPath: '# 借阅规则' });
  const child = chunk({ chunkId: 'B', text: 'b', headingPath: '# 借阅规则 > ## 续借' });
  const other = chunk({ chunkId: 'C', text: 'c', headingPath: '# 空间预约' });

  it('选父节点时含自身与所有后代', () => {
    expect(matchesHeading(parent, '借阅规则')).toBe(true);
    expect(matchesHeading(child, '借阅规则')).toBe(true);
    expect(matchesHeading(other, '借阅规则')).toBe(false);
  });

  it('选子节点时只含子节点', () => {
    expect(matchesHeading(child, '借阅规则 > 续借')).toBe(true);
    expect(matchesHeading(parent, '借阅规则 > 续借')).toBe(false);
  });

  it('同名不同层级不误判（借阅规则 vs 借阅规则2）', () => {
    const sibling = chunk({ chunkId: 'D', text: 'd', headingPath: '# 借阅规则2' });
    expect(matchesHeading(sibling, '借阅规则')).toBe(false);
  });

  it('未标注章节只能精确命中', () => {
    const bare = chunk({ chunkId: 'E', text: 'e', headingPath: '' });
    expect(matchesHeading(bare, '未标注章节')).toBe(true);
    expect(matchesHeading(bare, '借阅规则')).toBe(false);
  });
});

describe('关键词匹配（正文 / 标题 / 文档名 / 片段 ID）', () => {
  const item = chunk({
    chunkId: 'D02-C003',
    docTitle: '02_借阅规则.md',
    text: '普通图书在到期前可申请续借1次，续借增加7天。',
    headingPath: '# 借阅规则 > ## 续借',
  });

  it('正文命中（大小写不敏感）', () => {
    expect(matchesKeyword(item, '续借')).toBe(true);
    expect(matchesKeyword(chunk({ chunkId: 'X', text: 'Book Renewal' }), 'renewal')).toBe(true);
  });

  it('章节名命中', () => {
    expect(matchesKeyword(item, '借阅规则')).toBe(true);
  });

  it('文档名命中', () => {
    expect(matchesKeyword(item, '02_借阅')).toBe(true);
  });

  it('片段 ID 命中（大小写不敏感）', () => {
    expect(matchesKeyword(item, 'd02-c003')).toBe(true);
  });

  it('不命中返回 false，空关键词视为全通过', () => {
    expect(matchesKeyword(item, '赔偿金额')).toBe(false);
    expect(matchesKeyword(item, '   ')).toBe(true);
  });
});

describe('组合过滤', () => {
  const items = [
    chunk({ chunkId: 'D01-C001', docId: 'D01', text: '活动每周六举行', headingPath: '# 活动说明', kind: 'chunk' }),
    chunk({ chunkId: 'D02-C001', docId: 'D02', docTitle: '02_借阅规则.md', text: '借期21天', headingPath: '# 借阅规则', kind: 'chunk' }),
    chunk({ chunkId: 'D02-C002', docId: 'D02', docTitle: '02_借阅规则.md', text: '汇总：借阅要点', headingPath: '# 借阅规则', kind: 'summary' }),
  ];

  it('无筛选返回全部', () => {
    expect(filterChunks(items)).toHaveLength(3);
  });

  it('按文档', () => {
    expect(filterChunks(items, { docId: 'D02' }).map((c) => c.chunkId)).toEqual([
      'D02-C001',
      'D02-C002',
    ]);
  });

  it('按类型', () => {
    expect(filterChunks(items, { kind: 'summary' }).map((c) => c.chunkId)).toEqual(['D02-C002']);
  });

  it('文档 + 关键词 + 类型可叠加', () => {
    const out = filterChunks(items, { docId: 'D02', keyword: '借期', kind: 'chunk' });
    expect(out.map((c) => c.chunkId)).toEqual(['D02-C001']);
  });

  it('文档 + 章节前缀可叠加', () => {
    const out = filterChunks(items, { docId: 'D02', heading: '借阅规则' });
    expect(out).toHaveLength(2);
  });

  it('条件互斥时返回空数组而不是报错', () => {
    expect(filterChunks(items, { docId: 'D01', heading: '借阅规则' })).toEqual([]);
  });
});

describe('定位与相邻', () => {
  const items = [
    chunk({ chunkId: 'D02-C002', docId: 'D02', text: 'bbb', start: 150, end: 330 }),
    chunk({ chunkId: 'D02-C001', docId: 'D02', text: 'aaa', start: 0, end: 180 }),
    chunk({ chunkId: 'D02-C003', docId: 'D02', text: 'ccc', start: 300, end: 480 }),
    chunk({ chunkId: 'D01-C001', docId: 'D01', text: 'ddd', start: 0, end: 180 }),
  ];

  it('按 chunkId 定位（大小写不敏感）', () => {
    expect(indexOfChunk(items, 'd02-c002')).toBe(0);
    expect(indexOfChunk(items, 'D99-C999')).toBe(-1);
  });

  it('相邻三件套按 start 排序，不跨文档', () => {
    const hood = neighborhoodOf(items, 'D02-C002');
    expect(hood?.prev?.chunkId).toBe('D02-C001');
    expect(hood?.self.chunkId).toBe('D02-C002');
    expect(hood?.next?.chunkId).toBe('D02-C003');
  });

  it('首片段的 prev 为 null，末片段的 next 为 null', () => {
    expect(neighborhoodOf(items, 'D02-C001')?.prev).toBeNull();
    expect(neighborhoodOf(items, 'D02-C003')?.next).toBeNull();
  });

  it('找不到片段返回 null', () => {
    expect(neighborhoodOf(items, 'D99-C999')).toBeNull();
  });
});

describe('重叠字数（拓展 B 核心断言）', () => {
  it('180/30 切分下相邻片段重叠 30 字', () => {
    const text = '甲'.repeat(180) + '乙'.repeat(180);
    const first = chunk({ chunkId: 'A', text: text.slice(0, 180), start: 0, end: 180 });
    const second = chunk({ chunkId: 'B', text: text.slice(150, 330), start: 150, end: 330 });
    expect(overlapLength(first, second)).toBe(30);
  });

  it('完全不相邻时为 0', () => {
    const a = chunk({ chunkId: 'A', text: 'abcdef' });
    const b = chunk({ chunkId: 'B', text: 'ghijkl' });
    expect(overlapLength(a, b)).toBe(0);
  });

  it('adjacentPairs 按 start 排序后成对', () => {
    const items = [
      chunk({ chunkId: 'C', text: 'c', start: 300 }),
      chunk({ chunkId: 'A', text: 'a', start: 0 }),
      chunk({ chunkId: 'B', text: 'b', start: 150 }),
    ];
    const pairs = adjacentPairs(items);
    expect(pairs.map(([a, b]) => `${a.chunkId}-${b.chunkId}`)).toEqual(['A-B', 'B-C']);
  });
});

describe('片段拼接还原全文（F01 查看全文）', () => {
  it('重叠部分只保留一次', () => {
    // first 覆盖 0..9 = ABCDEFGHIJ；second 从 8 起覆盖 8..17 = IJKLMNOPQR，
    // 位置 8/9 的 "IJ" 是重叠，拼回去必须只有一份。
    const first = chunk({ chunkId: 'A', text: 'ABCDEFGHIJ', start: 0, end: 10 });
    const second = chunk({ chunkId: 'B', text: 'IJKLMNOPQR', start: 8, end: 18 });
    const merged = mergeChunks([second, first]);
    expect(merged.text).toBe('ABCDEFGHIJKLMNOPQR');
    expect(merged.gaps).toEqual([]);
  });

  it('空输入返回空串', () => {
    expect(mergeChunks([])).toEqual({ text: '', gaps: [] });
  });
});

describe('关键词高亮切片', () => {
  it('命中的片段标 hit=true', () => {
    const slices = splitHighlight('普通图书可申请续借，续借增加7天', '续借');
    expect(slices.filter((s) => s.hit).map((s) => s.text)).toEqual(['续借', '续借']);
  });

  it('大小写不敏感匹配但保留原文字', () => {
    const slices = splitHighlight('Book Renewal Book', 'renewal');
    expect(slices.find((s) => s.hit)?.text).toBe('Renewal');
  });

  it('空关键词整段不命中', () => {
    expect(splitHighlight('abc', '')).toEqual([{ text: 'abc', hit: false }]);
  });

  it('空文本返回空数组', () => {
    expect(splitHighlight('', 'x')).toEqual([]);
  });

  it('正则元字符被转义（关键词 . * + 不会炸）', () => {
    expect(() => splitHighlight('a.b*c+d', '.*+')).not.toThrow();
    expect(splitHighlight('a.b*c+d', '.*+').some((s) => s.hit)).toBe(false);
  });
});
