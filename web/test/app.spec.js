import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import App from '../src/App.vue';
import { state } from '../src/store.js';

/**
 * 整棵树挂载冒烟测试。
 * 目的不是覆盖每个交互，而是保证「所有组件都能被解析、import 路径都对、首次 refresh 后界面有内容」——
 * 单测各自 mount 一个组件时，像 ChatTurn 引错 AnswerBlock 这种路径错误是发现不了的（vitest 只加载被引到的模块）。
 */

const STATUS = {
  provider: 'mock',
  mock: true,
  chunk_size: 180,
  chunk_overlap: 30,
  top_k: 3,
  docs: [
    { name: '01_活动说明.md', chars: 304, chunks: 2, verified: true },
    { name: '06_成员留言摘录.md', chars: 369, chunks: 3, verified: false },
  ],
  doc_count: 6,
  ready: true,
  stale: false,
  chunks: 15,
  message: '',
  build: { stage: 'idle', done: 0, total: 0, error: '' },
  session: { session_id: 'abc123def456', history: 0, mode: 'rag', k: 3 },
  has_keys: false,
  k_range: [1, 5],
  config: { model: '', embedding_model: '' },
  examples: ['读书会通常在每周几几点举行？', '参加读书会要交多少费用？'],
};

function stubFetch() {
  global.fetch = vi.fn(async (path) => {
    const map = {
      '/api/status': STATUS,
      '/api/chunks': { chunks: [], size: 180, overlap: 30, total: 0 },
      '/api/logs/last': { empty: true, messages: [] },
      '/api/batch/progress': { stage: 'idle', done: 0, total: 0, rows: [], stats: { total: 0, direct: 0, rag: 0 } },
    };
    const body = map[String(path).split('?')[0]] || {};
    return { ok: true, status: 200, json: async () => body };
  });
}

beforeEach(() => {
  state.status = null;
  state.turns = [];
  state.view = 'chat';
  state.lastTrace = [];
  state.lastMessages = [];
  state.batchRows = [];
  state.batchState = null;
  stubFetch();
});

describe('App 挂载冒烟', () => {
  it('首屏渲染侧栏、状态徽章、示例问题与输入框', async () => {
    const wrapper = mount(App, { attachTo: document.body });
    await flushPromises();

    expect(wrapper.find('.brand h1').text()).toBe('星河读书会');
    expect(wrapper.text()).toContain('知识库就绪 · 15 片段');
    expect(wrapper.text()).toContain('资料 6 份 · 分块 180/30');
    expect(wrapper.text()).toContain('01_活动说明.md');
    expect(wrapper.text()).toContain('未核实');
    expect(wrapper.findAll('.chip')).toHaveLength(2);
    expect(wrapper.find('textarea.question').exists()).toBe(true);
    expect(wrapper.text()).toContain('先在左侧建库，再提一个问题试试。');

    wrapper.unmount();
  });

  it('切换 tab 只显示对应视图，输入区仅在对话视图', async () => {
    const wrapper = mount(App, { attachTo: document.body });
    await flushPromises();

    expect(wrapper.find('textarea.question').isVisible()).toBe(true);

    const tabs = wrapper.findAll('.tab');
    expect(tabs.map((t) => t.text())).toEqual(['对话', '检索过程', '片段浏览', '批量对照']);

    await tabs[3].trigger('click');
    await flushPromises();
    expect(state.view).toBe('batch');
    expect(wrapper.find('textarea.question').isVisible()).toBe(false);
    expect(wrapper.text()).toContain('初判由关键词规则自动给出，仅作参考，报告里仍需人工核对并写明误判情况。');

    await tabs[0].trigger('click');
    await flushPromises();
    expect(state.view).toBe('chat');
    expect(wrapper.find('textarea.question').isVisible()).toBe(true);

    wrapper.unmount();
  });

  it('发送问题后出现用户气泡与回答气泡', async () => {
    const wrapper = mount(App, { attachTo: document.body });
    await flushPromises();

    global.fetch = vi.fn(async (path) => {
      if (String(path) === '/api/chat') {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            mode: 'rag',
            answer: '已登记成员每人最多同时借阅4本普通图书，每本借期21天。[D02-C001]',
            citations: [{
              ref: 1,
              chunk_id: 'D02-C001',
              source: '02_借阅规则.md',
              score: 0.8342,
              start: 0,
              end: 180,
              verified: true,
              excerpt: '已登记成员每人最多同时借阅4本普通图书，每本借期21天。',
              text: '已登记成员每人最多同时借阅4本普通图书，每本借期21天。',
            }],
            trace: [{ rank: 1, chunk_id: 'D02-C001', source: '02_借阅规则.md', score: 0.8342, verified: true, retrieved: true, excerpt: '…' }],
            used_knowledge_base: true,
            removed_citations: [],
            elapsed_ms: 9,
            session: STATUS.session,
          }),
        };
      }
      return { ok: true, status: 200, json: async () => (String(path) === '/api/status' ? STATUS : {}) };
    });

    await wrapper.find('textarea.question').setValue('普通图书最多同时借阅几本借多久？');
    await wrapper.find('.input-row .btn').trigger('click');
    await flushPromises();

    expect(wrapper.find('.bubble.user').text()).toBe('普通图书最多同时借阅几本借多久？');
    expect(wrapper.find('.cite').text()).toBe('[D02-C001]');
    expect(wrapper.find('.card .src').text()).toBe('02_借阅规则.md');
    expect(wrapper.find('.honesty').text()).toContain('引用只表示取回来源，仍需核对原文');

    wrapper.unmount();
  });
});
