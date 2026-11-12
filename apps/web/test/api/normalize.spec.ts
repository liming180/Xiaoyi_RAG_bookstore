import { describe, expect, it } from 'vitest';
import { normalizeCitation, normalizeCitations, normalizeDocument, normalizeIndexStatus } from '@/api/normalize';

describe('契约归一化：Citation 双形状', () => {
  it('吃下规格 §7.5 形状（ref 为片段 ID）', () => {
    const c = normalizeCitation({
      ref: 'D02-C001',
      docId: 'D02',
      docTitle: '02_借阅规则.md',
      headingPath: '# 星河读书会借阅规则',
      chunk: '已登记成员每人最多同时借阅4本普通图书',
      start: 120,
      end: 180,
      score: 0.87,
      stage: 'rerank',
    });
    expect(c.ref).toBe('D02-C001');
    expect(c.chunkId).toBe('D02-C001');
    expect(c.docTitle).toBe('02_借阅规则.md');
    expect(c.text).toContain('4本');
    expect(c.kind).toBe('chunk');
  });

  it('吃下功能规格 F05 形状（ref 为数字 + snake_case）', () => {
    const c = normalizeCitation({
      ref: 1,
      chunk_id: 'D02-C001',
      source: '02_借阅规则.md',
      score: 0.91,
      start: 0,
      end: 180,
      text: '片段正文',
    });
    expect(c.ref).toBe(1);
    expect(c.chunkId).toBe('D02-C001');
    expect(c.docTitle).toBe('02_借阅规则.md');
    expect(c.text).toBe('片段正文');
  });

  it('缺失 ref 时按序号补 1..k', () => {
    const list = normalizeCitations([{ chunk: 'a' }, { chunk: 'b' }]);
    expect(list.map((c) => c.ref)).toEqual([1, 2]);
  });

  it('识别 summary / rule 类型', () => {
    expect(normalizeCitation({ kind: 'summary' }).kind).toBe('summary');
    expect(normalizeCitation({ kind: 'rule' }).kind).toBe('rule');
    expect(normalizeCitation({ kind: 'unknown' }).kind).toBe('chunk');
  });
});

describe('契约归一化：Document / IndexStatus', () => {
  it('文档状态白名单外的值降级为 INDEXED', () => {
    expect(normalizeDocument({ name: 'a.md', status: 'weird' }).status).toBe('INDEXED');
    expect(normalizeDocument({ name: 'a.md', status: 'needs_rebuild' }).status).toBe('NEEDS_REBUILD');
  });

  it('06 成员留言默认未核实', () => {
    expect(normalizeDocument({ name: '06_成员留言摘录.md' }).verified).toBe(false);
    expect(normalizeDocument({ name: '01_活动说明.md' }).verified).toBe(true);
  });

  it('索引状态只接受三态', () => {
    expect(normalizeIndexStatus({ status: 'ready' }).status).toBe('ready');
    expect(normalizeIndexStatus({ status: 'needs_rebuild' }).status).toBe('needs_rebuild');
    expect(normalizeIndexStatus({ status: 'oops' }).status).toBe('unavailable');
  });

  it('snake_case 字段可读', () => {
    const s = normalizeIndexStatus({ status: 'ready', doc_count: 6, chunk_count: 15, chunk_size: 180, chunk_overlap: 30 });
    expect(s).toMatchObject({ docCount: 6, chunkCount: 15, chunkSize: 180, overlap: 30 });
  });
});
