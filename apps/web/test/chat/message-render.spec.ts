import { beforeEach, describe, expect, it } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import ElementPlus from 'element-plus';
import MessageList from '@/features/chat/components/MessageList.vue';
import AnswerBody from '@/features/chat/components/AnswerBody.vue';
import MessageBubble from '@/features/chat/components/MessageBubble.vue';
import type { Citation, Message } from '@/types/api';
import { resetState } from '@/mocks/state';
import { T03_ANSWER, seedCitations } from '@/mocks/data';

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', redirect: '/chat' },
      { path: '/chat', name: 'chat', component: { template: '<div />' } },
      { path: '/knowledge/chunks', name: 'chunks', component: { template: '<div />' } },
      { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
    ],
  });
}

function assistant(content: string, citations: Citation[], over: Partial<Message> = {}): Message {
  return {
    id: 'm-a1',
    conversationId: 'c-demo',
    role: 'assistant',
    content,
    createdAt: Date.now(),
    citations,
    trace: null,
    usage: null,
    elapsedMs: 2340,
    degraded: false,
    suggestions: [],
    feedback: null,
    ...over,
  };
}

function user(content: string): Message {
  return {
    id: 'm-u1',
    conversationId: 'c-demo',
    role: 'user',
    content,
    createdAt: Date.now(),
    citations: [],
    trace: null,
    usage: null,
    elapsedMs: null,
    degraded: false,
    suggestions: [],
    feedback: null,
  };
}

function mountList(messages: Message[]) {
  const router = makeRouter();
  return mount(MessageList, {
    props: { messages },
    global: { plugins: [ElementPlus, router] },
  });
}

describe('消息渲染（F04）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('用户与助手气泡分别渲染，助手带耗时', () => {
    const citations = seedCitations(1);
    const wrapper = mountList([user('最多借几本？'), assistant(T03_ANSWER, citations)]);
    expect(wrapper.findAll('[data-testid="msg-user"]')).toHaveLength(1);
    expect(wrapper.findAll('[data-testid="msg-assistant"]')).toHaveLength(1);
    expect(wrapper.get('[data-testid="msg-elapsed"]').text()).toContain('2.3 s');
    expect(wrapper.text()).toContain('4本');
    expect(wrapper.text()).toContain('21天');
  });

  it('空消息列表显示空态', () => {
    const wrapper = mountList([]);
    expect(wrapper.find('[data-testid="message-empty"]').exists()).toBe(true);
  });

  it('表格被渲染成真正的 table 元素', () => {
    const wrapper = mount(AnswerBody, {
      props: { content: T03_ANSWER, citations: seedCitations(1) },
      global: { plugins: [ElementPlus] },
    });
    expect(wrapper.findAll('table').length).toBe(1);
    // T03_ANSWER 的表格是「项目 | 规则」两列、三行数据
    expect(wrapper.findAll('th').length).toBe(2);
    expect(wrapper.findAll('tbody tr').length).toBe(3);
    expect(wrapper.text()).toContain('同时借阅上限');
  });

  it('回答里的 img onerror 被当作纯文本，不生成 img 元素', () => {
    const wrapper = mount(AnswerBody, {
      props: {
        content: '资料里夹带 <img src=x onerror="window.__pwned=1"> 指令',
        citations: [],
      },
      global: { plugins: [ElementPlus] },
    });
    expect(wrapper.findAll('img')).toHaveLength(0);
    expect(wrapper.text()).toContain('<img');
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
  });
});

describe('引用卡（F05）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('点击有效编号打开引用卡，展示五要素', async () => {
    const citations = seedCitations(1);
    const wrapper = mountList([user('最多借几本？'), assistant(T03_ANSWER, citations)]);

    const badge = wrapper.find('[data-testid="cite-badge"]');
    expect(badge.exists()).toBe(true);
    await badge.trigger('click');
    await flushPromises();

    const card = wrapper.get('[data-testid="cite-card-wrap"]');
    expect(card.text()).toContain(citations[0]!.docTitle);
    expect(card.text()).toContain(citations[0]!.chunkId);
    expect(card.text()).toContain('第 1 字至第');
    expect(card.find('[data-testid="cite-excerpt"]').exists()).toBe(true);
  });

  it('引用卡可以关闭', async () => {
    const wrapper = mountList([assistant(T03_ANSWER, seedCitations(1))]);
    await wrapper.get('[data-testid="cite-badge"]').trigger('click');
    await flushPromises();
    expect(wrapper.find('[data-testid="cite-card-wrap"]').exists()).toBe(true);

    await wrapper.get('[aria-label="关闭引用卡"]').trigger('click');
    await flushPromises();
    expect(wrapper.find('[data-testid="cite-card-wrap"]').exists()).toBe(false);
  });

  it('展开完整片段显示原文', async () => {
    const wrapper = mountList([assistant(T03_ANSWER, seedCitations(1))]);
    await wrapper.get('[data-testid="cite-badge"]').trigger('click');
    await flushPromises();
    expect(wrapper.find('[data-testid="cite-full"]').exists()).toBe(false);

    const toggle = wrapper.findAll('button').find((b) => b.text() === '展开完整片段');
    expect(toggle).toBeTruthy();
    await toggle!.trigger('click');
    await flushPromises();
    expect(wrapper.find('[data-testid="cite-full"]').exists()).toBe(true);
  });

  it('幻觉编号渲染为灰色不可点', () => {
    // 文本里有 [9]，但 citations 只有 ref=1
    const wrapper = mountList([assistant('这条结论来自 [9]。', seedCitations(1))]);
    const ghost = wrapper.find('[data-testid="cite-badge-ghost"]');
    expect(ghost.exists()).toBe(true);
    expect(ghost.attributes('disabled')).toBeDefined();
    expect(ghost.classes()).toContain('source-ref--ghost');
  });

  it('kind=summary 显示全局汇总徽标', async () => {
    const summary: Citation = {
      ...seedCitations(1)[0]!,
      ref: 1,
      chunkId: 'D02-S001',
      kind: 'summary',
      docTitle: '全局摘要',
    };
    const wrapper = mountList([assistant('整体情况见 [1]。', [summary])]);
    await wrapper.get('[data-testid="cite-badge"]').trigger('click');
    await flushPromises();
    expect(wrapper.get('[data-testid="cite-card-wrap"]').text()).toContain('🌐 全局汇总');
  });

  it('未核实资料在引用卡里显示「未核实」标签', async () => {
    const unverified: Citation = { ...seedCitations(5)[0]!, verified: false };
    const wrapper = mountList([assistant('留言里提到 [1]。', [unverified])]);
    await wrapper.get('[data-testid="cite-badge"]').trigger('click');
    await flushPromises();
    expect(wrapper.find('[data-testid="cite-unverified"]').exists()).toBe(true);
  });
});

describe('消息元信息（F04/F11）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('degraded=true 时显示降级警示条', () => {
    const wrapper = mount(MessageBubble, {
      props: { message: assistant('直接回答。', [], { degraded: true }) },
      global: { plugins: [ElementPlus] },
    });
    expect(wrapper.find('[data-testid="msg-degraded"]').exists()).toBe(true);
  });

  it('引用含未核实资料时显示提醒条', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: assistant('留言提到 [1]。', [{ ...seedCitations(5)[0]!, verified: false }]),
      },
      global: { plugins: [ElementPlus] },
    });
    expect(wrapper.find('[data-testid="unverified-warn"]').exists()).toBe(true);
  });

  it('suggestions 缺失时不渲染追问区也不报错', () => {
    const msg = assistant('回答。', []);
    delete (msg as Partial<Message>).suggestions;
    const wrapper = mount(MessageBubble, {
      props: { message: msg },
      global: { plugins: [ElementPlus] },
    });
    expect(wrapper.find('[data-testid="msg-suggestions"]').exists()).toBe(false);
  });

  it('suggestions 存在时渲染 chips 并上抛点击', async () => {
    const wrapper = mount(MessageBubble, {
      props: { message: assistant('回答。', [], { suggestions: ['续借几天？', '怎么预约？'] }) },
      global: { plugins: [ElementPlus] },
    });
    const chips = wrapper.findAll('.bubble__chip');
    expect(chips).toHaveLength(2);
    await chips[0]!.trigger('click');
    expect(wrapper.emitted('suggest')?.[0]).toEqual(['续借几天？']);
  });
});
