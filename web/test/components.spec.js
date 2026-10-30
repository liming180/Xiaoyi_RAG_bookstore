import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import AnswerBlock from '../src/components/AnswerBlock.vue';
import AnswerText from '../src/components/AnswerText.vue';
import SourceCard from '../src/components/SourceCard.vue';
import TraceView from '../src/components/views/TraceView.vue';
import { state } from '../src/store.js';

const CARD = {
  ref: 1,
  chunk_id: 'D02-C001',
  source: '02_借阅规则.md',
  score: 0.8342,
  start: 0,
  end: 180,
  verified: true,
  excerpt: '已登记成员每人最多同时借阅4本普通图书，每本借期21天。',
  text: '已登记成员每人最多同时借阅4本普通图书，每本借期21天。被其他成员预约的图书不能续借。',
};

describe('AnswerText', () => {
  it('有效编号渲染成 .cite 并可点击', async () => {
    const wrapper = mount(AnswerText, {
      props: { text: '最多借阅4本。[1]', citations: [CARD] },
    });
    const cite = wrapper.find('.cite');
    expect(cite.exists()).toBe(true);
    expect(cite.attributes('data-chunk')).toBe('D02-C001');
    expect(cite.text()).toBe('[1]');
    await cite.trigger('click');
    expect(state.flashChunkId).toBe('D02-C001');
  });

  it('无效编号保持纯文本', () => {
    const wrapper = mount(AnswerText, {
      props: { text: '结论 [9]', citations: [CARD] },
    });
    expect(wrapper.find('.cite').exists()).toBe(false);
    expect(wrapper.text()).toContain('[9]');
  });
});

describe('SourceCard', () => {
  it('渲染编号、文件名、得分、位置与原文折叠', () => {
    const wrapper = mount(SourceCard, { props: { card: CARD, index: 0, question: '借阅' } });
    expect(wrapper.attributes('id')).toBe('card-D02-C001');
    expect(wrapper.find('.idx').text()).toBe('[1]');
    expect(wrapper.find('.src').text()).toBe('02_借阅规则.md');
    expect(wrapper.text()).toContain('0.8342');
    expect(wrapper.text()).toContain('第 1–180 字');
    expect(wrapper.find('details pre').text()).toContain('不能续借');
    expect(wrapper.find('mark').text()).toBe('借阅');
  });

  it('未核实资料加 unverified 样式与徽章', () => {
    const wrapper = mount(SourceCard, {
      props: { card: { ...CARD, verified: false }, index: 1, question: '' },
    });
    expect(wrapper.classes()).toContain('unverified');
    expect(wrapper.find('.badge.warn').text()).toBe('未核实');
  });
});

describe('AnswerBlock', () => {
  const payload = {
    mode: 'rag',
    answer: '最多同时借阅4本普通图书，每本借期21天。[D02-C001]',
    citations: [CARD],
    used_knowledge_base: true,
    removed_citations: [],
    elapsed_ms: 15,
  };

  it('单模式渲染回答、来源卡与诚实提示', () => {
    const wrapper = mount(AnswerBlock, { props: { payload, question: '借阅' } });
    expect(wrapper.find('.cite').exists()).toBe(true);
    expect(wrapper.find('.card').exists()).toBe(true);
    const honesty = wrapper.find('.honesty').text();
    expect(honesty).toContain('耗时 15 ms');
    expect(honesty).toContain('引用只表示取回来源，仍需核对原文');
  });

  it('未取回片段时提示「本轮没有取回任何片段」', () => {
    const wrapper = mount(AnswerBlock, {
      props: {
        payload: { ...payload, answer: '资料中没有提供收费标准。', citations: [], used_knowledge_base: false },
        question: '费用',
      },
    });
    expect(wrapper.find('.honesty').text()).toContain('本轮没有取回任何片段');
  });

  it('剔除无效编号时列出编号', () => {
    const wrapper = mount(AnswerBlock, {
      props: { payload: { ...payload, removed_citations: ['9', '12'] }, question: '借阅' },
    });
    expect(wrapper.find('.honesty').text()).toContain('已剔除无效编号 9、12');
  });

  it('both 模式并排两列，不查资料侧标未引用', () => {
    const wrapper = mount(AnswerBlock, {
      props: {
        payload: {
          mode: 'both',
          rag: { answer: '查资料答案。[1]', citations: [CARD] },
          direct: { answer: '不查资料答案。' },
          elapsed_ms: 30,
        },
        question: '借阅',
      },
    });
    const heads = wrapper.findAll('.col-head').map((h) => h.text());
    expect(heads[0]).toContain('查资料');
    expect(heads[0]).toContain('已引用知识库');
    expect(heads[1]).toContain('不查资料');
    expect(heads[1]).toContain('未引用知识库资料');
    expect(wrapper.findAll('.answer-col')).toHaveLength(2);
  });
});

describe('TraceView', () => {
  /* TraceView 挂载时会拉 /api/logs/last，这里给一个不联网的桩，避免 jsdom 真的发请求 */
  beforeEach(() => {
    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ messages: [] }),
    }));
  });

  it('前 k 行加 retrieved，第 k 行加 cut', () => {
    state.lastTrace = [
      { rank: 1, chunk_id: 'D01-C001', source: '01_活动说明.md', score: 0.81, verified: true, retrieved: true, excerpt: 'a' },
      { rank: 2, chunk_id: 'D02-C001', source: '02_借阅规则.md', score: 0.62, verified: true, retrieved: true, excerpt: 'b' },
      { rank: 3, chunk_id: 'D03-C001', source: '03_空间预约.md', score: 0.41, verified: false, retrieved: false, excerpt: 'c' },
    ];
    state.lastMessages = [{ role: 'user', content: '问' }];
    const wrapper = mount(TraceView);
    const rows = wrapper.findAll('tbody tr');
    expect(rows).toHaveLength(4);
    expect(rows[0].classes()).toContain('retrieved');
    expect(rows[1].classes()).toContain('retrieved');
    expect(rows[1].classes()).toContain('cut');
    expect(rows[2].classes()).not.toContain('retrieved');
    expect(wrapper.text()).toContain('0.8100');
    expect(wrapper.text()).toContain('未核实');
  });

  it('无记录时显示空态', () => {
    state.lastTrace = [];
    state.lastMessages = [];
    const wrapper = mount(TraceView);
    expect(wrapper.text()).toContain('还没有检索记录');
  });
});
