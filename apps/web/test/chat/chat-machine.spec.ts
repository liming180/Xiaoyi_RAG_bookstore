import { describe, expect, it } from 'vitest';
import {
  abort,
  failWith,
  hasDraft,
  initialState,
  pendingLabel,
  reduce,
  reduceAll,
} from '@/features/chat/composables/chatMachine';
import type { ChatStreamEvent, Citation } from '@/types/api';

const citation: Citation = {
  ref: 1,
  chunkId: 'D02-C001',
  docId: 'D02',
  docTitle: '02_借阅规则.md',
  headingPath: '借阅数量',
  text: '每人最多同时借阅 4 本。',
  start: 0,
  end: 20,
  score: 0.87,
  kind: 'chunk',
  verified: true,
};

function status(stage: string): ChatStreamEvent {
  return { event: 'status', data: { stage } } as ChatStreamEvent;
}
function token(content: string): ChatStreamEvent {
  return { event: 'token', data: { content } } as ChatStreamEvent;
}

describe('对话状态机（F04）', () => {
  it('正常序列：status → retrieval → token* → done', () => {
    const s = reduceAll([
      status('rewriting'),
      status('retrieving'),
      { event: 'retrieval', data: { citations: [citation] } } as ChatStreamEvent,
      status('generating'),
      token('最多借 '),
      token('4 本'),
      {
        event: 'done',
        data: {
          messageId: 'm-1',
          elapsedMs: 1800,
          suggestions: ['续借几天？', 123, '怎么预约？'],
        },
      } as ChatStreamEvent,
    ]);

    expect(s.phase).toBe('done');
    expect(s.draft).toBe('最多借 4 本');
    expect(s.citations).toHaveLength(1);
    expect(s.messageId).toBe('m-1');
    expect(s.elapsedMs).toBe(1800);
    // 非字符串 suggestion 被过滤，最多 3 条
    expect(s.suggestions).toEqual(['续借几天？', '怎么预约？']);
    expect(s.stage).toBeNull();
  });

  it('双加载态文案随 status 阶段切换', () => {
    let s = reduce(initialState(), status('retrieving'));
    expect(pendingLabel(s)).toBe('正在检索资料…');
    s = reduce(s, status('reranking'));
    expect(pendingLabel(s)).toBe('正在重排结果…');
    s = reduce(s, status('generating'));
    expect(pendingLabel(s)).toBe('正在回答…');
    expect(hasDraft(s)).toBe(false);
  });

  it('idle / done 时没有等待文案', () => {
    expect(pendingLabel(initialState())).toBe('');
    const done = reduceAll([token('a'), { event: 'done', data: { messageId: 'm' } } as ChatStreamEvent]);
    expect(pendingLabel(done)).toBe('');
  });

  it('中途 error：进入 error 态并保留已生成正文', () => {
    const s = reduceAll([
      token('前半段'),
      { event: 'error', data: { code: 50001, message: '模型超时' } } as ChatStreamEvent,
    ]);
    expect(s.phase).toBe('error');
    expect(s.error).toMatchObject({ code: 50001, message: '模型超时' });
    expect(s.draft).toBe('前半段');
    expect(s.stage).toBeNull();
  });

  it('error 事件缺字段时给兜底文案', () => {
    const s = reduce(initialState(), { event: 'error', data: {} } as ChatStreamEvent);
    expect(s.error?.code).toBe(50000);
    expect(s.error?.message).toBe('生成失败，请重试');
  });

  it('未知事件 identity 透传，不中断也不改业务状态', () => {
    const base = reduceAll([token('abc')]);
    const after = reduce(base, { event: 'heartbeat', data: { ts: 1 } } as ChatStreamEvent);
    expect(after.draft).toBe('abc');
    expect(after.phase).toBe(base.phase);
    expect(after.unknownEvents).toBe(1);

    const after2 = reduce(after, { event: 'weird', data: null } as ChatStreamEvent);
    expect(after2.unknownEvents).toBe(2);
    expect(after2.draft).toBe('abc');
  });

  it('degraded=true 记录在状态里', () => {
    const s = reduceAll([
      { event: 'done', data: { messageId: 'm', degraded: true } } as ChatStreamEvent,
    ]);
    expect(s.degraded).toBe(true);
  });

  it('done 之后再来 token 被忽略（尾部脏帧）', () => {
    const s = reduceAll([
      token('完整'),
      { event: 'done', data: { messageId: 'm' } } as ChatStreamEvent,
      token('多余'),
    ]);
    expect(s.draft).toBe('完整');
    expect(s.phase).toBe('done');
  });

  it('token 缺 content 字段不产生脏字符', () => {
    const s = reduceAll([
      token('ok'),
      { event: 'token', data: {} } as ChatStreamEvent,
      { event: 'token', data: { content: 42 } } as ChatStreamEvent,
    ]);
    expect(s.draft).toBe('ok');
  });

  it('retrieval 的 citations 非数组时保持原状', () => {
    const s = reduceAll([
      { event: 'retrieval', data: { citations: [citation] } } as ChatStreamEvent,
      { event: 'retrieval', data: { citations: 'oops' } } as ChatStreamEvent,
    ]);
    expect(s.citations).toHaveLength(1);
  });

  it('abort 保留已生成内容且不进错误态', () => {
    const s = abort(reduceAll([token('半截话')]));
    expect(s.phase).toBe('done');
    expect(s.draft).toBe('半截话');
    expect(s.error).toBeNull();
  });

  it('failWith 把网络异常统一成错误态', () => {
    const s = failWith(initialState(), '网络异常，请重试');
    expect(s.phase).toBe('error');
    expect(s.error?.message).toBe('网络异常，请重试');
  });
});
