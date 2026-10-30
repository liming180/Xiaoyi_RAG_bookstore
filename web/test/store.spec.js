import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { actions, indexHint, kbBadge, state } from '../src/store.js';

/** 造一个最小的 fetch 桩：按调用顺序返回预设响应，并记录 (path, init) */
function stubFetch(responses) {
  const calls = [];
  const queue = [...responses];
  global.fetch = vi.fn(async (path, init) => {
    calls.push({ path, init });
    const next = queue.shift();
    if (!next) throw new Error(`未预置的请求：${path}`);
    const body = next.body === undefined ? {} : next.body;
    return {
      ok: next.ok !== false,
      status: next.status || 200,
      json: async () => body,
    };
  });
  return calls;
}

const STATUS = {
  provider: 'mock',
  mock: true,
  chunk_size: 180,
  chunk_overlap: 30,
  top_k: 3,
  docs: [],
  doc_count: 6,
  ready: true,
  stale: false,
  chunks: 15,
  message: '',
  build: { stage: 'idle', done: 0, total: 0, error: '' },
  session: { session_id: 'abc123', history: 0, mode: 'rag', k: 3 },
  has_keys: false,
  k_range: [1, 5],
  config: {},
  examples: ['读书会通常在每周几几点举行？'],
};

beforeEach(() => {
  state.status = null;
  state.docs = [];
  state.mode = 'rag';
  state.k = 3;
  state.view = 'chat';
  state.turns = [];
  state.lastTrace = [];
  state.batchRows = [];
  state.batchState = null;
  state.busy = false;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('kbBadge / indexHint', () => {
  it('三态徽章文案', () => {
    expect(kbBadge(null).text).toBe('知识库未就绪');
    expect(kbBadge({ ready: true, chunks: 15 })).toEqual({ cls: 'badge', text: '知识库就绪 · 15 片段' });
    expect(kbBadge({ ready: false, stale: true }).text).toBe('需要重新建库');
    expect(kbBadge({ ready: false, stale: false }).text).toBe('知识库未建库');
  });

  it('建库提示四分支', () => {
    expect(indexHint({ build: { stage: 'running', done: 5, total: 20 } })).toEqual({
      bar: '25%',
      text: '正在建库 5/20 片段…',
    });
    expect(indexHint({ build: { stage: 'error', error: '接口超时' } }).text).toBe('建库失败：接口超时');
    expect(indexHint({ ready: true, doc_count: 6, chunks: 15 }).text).toBe('建库成功，文档 6 份，片段 15 条。');
    expect(indexHint({ ready: false, stale: true, message: '资料已改变。' }).text).toBe('资料已改变。');
    expect(indexHint({ ready: false, stale: false }).text).toBe('尚未建库，点击“重新建库”。');
  });
});

describe('refresh', () => {
  it('拉 /api/status 并回写 mode/k/docs', async () => {
    const calls = stubFetch([{ body: STATUS }]);
    await actions.refresh();
    expect(calls[0].path).toBe('/api/status');
    expect(state.status.chunks).toBe(15);
    expect(state.mode).toBe('rag');
    expect(state.k).toBe(3);
  });
});

describe('buildIndex', () => {
  it('先 POST /api/config 再 POST /api/index', async () => {
    const calls = stubFetch([{ body: { ok: true } }, { body: { started: true } }]);
    await actions.buildIndex(120, 30);
    expect(calls.map((c) => c.path)).toEqual(['/api/config', '/api/index']);
    expect(JSON.parse(calls[0].init.body)).toEqual({ chunk_size: 120, chunk_overlap: 30 });
  });

  it('前端先拦非法参数，不打后端', async () => {
    const calls = stubFetch([]);
    await expect(actions.buildIndex(20, 10)).rejects.toThrow('片段长度须在 50 至 1000 之间');
    await expect(actions.buildIndex(180, 180)).rejects.toThrow('重叠字数须满足 0 <= 重叠 < 片段长度');
    expect(calls).toHaveLength(0);
  });
});

describe('send', () => {
  it('成功后写入 turn 与 lastTrace，busy 复位', async () => {
    const payload = {
      mode: 'rag',
      answer: '最多同时借阅4本普通图书。[D02-C001]',
      citations: [{ ref: 1, chunk_id: 'D02-C001', source: '02_借阅规则.md', score: 0.83 }],
      trace: [{ rank: 1, chunk_id: 'D02-C001', retrieved: true }],
      used_knowledge_base: true,
      removed_citations: [],
      elapsed_ms: 12,
      session: { session_id: 'abc123', history: 2, mode: 'rag', k: 3 },
    };
    stubFetch([{ body: payload }, { body: STATUS }]);
    await actions.send('普通图书最多同时借阅几本借多久？');
    expect(state.turns).toHaveLength(1);
    expect(state.turns[0].status).toBe('done');
    expect(state.lastTrace).toHaveLength(1);
    expect(state.busy).toBe(false);
  });

  it('失败时 turn.status=fail、busy 复位、错误可读', async () => {
    stubFetch([{ ok: false, status: 400, body: { detail: '尚未建库，请先点击“重新建库”。' } }, { body: STATUS }]);
    await expect(actions.send('随便问')).rejects.toThrow('尚未建库');
    expect(state.turns[0].status).toBe('fail');
    expect(state.turns[0].error).toBe('尚未建库，请先点击“重新建库”。');
    expect(state.busy).toBe(false);
  });

  it('空问题直接返回，不产生气泡', async () => {
    stubFetch([]);
    expect(await actions.send('   ')).toBeNull();
    expect(state.turns).toHaveLength(0);
  });
});

describe('newSession', () => {
  it('清空 turns 与 lastTrace', async () => {
    state.turns = [{ id: 1, question: 'x' }];
    state.lastTrace = [{ rank: 1 }];
    state.status = { session: { session_id: 'old' } };
    stubFetch([{ body: { session_id: 'new1', mode: 'rag', k: 3, history: 0 } }]);
    await actions.newSession();
    expect(state.turns).toEqual([]);
    expect(state.lastTrace).toEqual([]);
    expect(state.status.session.session_id).toBe('new1');
  });
});
