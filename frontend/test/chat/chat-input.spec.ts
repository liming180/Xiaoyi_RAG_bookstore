import { beforeEach, describe, expect, it } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus from 'element-plus';
import ChatInput from '@/features/chat/components/ChatInput.vue';
import RetrievalTrace from '@/features/chat/components/RetrievalTrace.vue';
import type { RetrievalTrace as TraceType } from '@/types/api';
import { resetState } from '@/mocks/state';
import { seedTrace } from '@/mocks/data';

describe('输入区（F04）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  function mountInput(over: Record<string, unknown> = {}) {
    return mount(ChatInput, {
      props: { mode: 'rag' as const, k: 3, ...over },
      global: { plugins: [ElementPlus] },
    });
  }

  it('Enter 发送，Shift+Enter 不发送', async () => {
    const wrapper = mountInput();
    const ta = wrapper.get('[data-testid="question-input"]');
    await ta.setValue('读书会什么时候举行？');

    await ta.trigger('keydown', { key: 'Enter', shiftKey: true });
    expect(wrapper.emitted('send')).toBeUndefined();

    await ta.trigger('keydown', { key: 'Enter' });
    const sent = wrapper.emitted('send');
    expect(sent).toHaveLength(1);
    expect(sent?.[0]).toEqual(['读书会什么时候举行？']);
  });

  it('输入法组合期按 Enter 不发送', async () => {
    const wrapper = mountInput();
    const ta = wrapper.get('[data-testid="question-input"]');
    await ta.setValue('读书会');
    await ta.trigger('compositionstart');
    await ta.trigger('keydown', { key: 'Enter' });
    expect(wrapper.emitted('send')).toBeUndefined();
    await ta.trigger('compositionend');
    await ta.trigger('keydown', { key: 'Enter' });
    expect(wrapper.emitted('send')).toHaveLength(1);
  });

  it('空内容不发送，发送按钮禁用', async () => {
    const wrapper = mountInput();
    const btn = wrapper.get('[data-testid="chat-send"]');
    expect(btn.attributes('disabled')).toBeDefined();
    await wrapper.get('[data-testid="question-input"]').setValue('   ');
    expect(btn.attributes('disabled')).toBeDefined();
  });

  it('maxlength 限制为 1000', () => {
    const wrapper = mountInput();
    expect(wrapper.get('[data-testid="question-input"]').attributes('maxlength')).toBe('1000');
  });

  it('流式期间显示停止按钮并禁用发送', async () => {
    const wrapper = mountInput({ streaming: true });
    expect(wrapper.find('[data-testid="chat-stop"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="chat-send"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="question-input"]').attributes('aria-busy')).toBe('true');

    await wrapper.get('[data-testid="chat-stop"]').trigger('click');
    expect(wrapper.emitted('stop')).toHaveLength(1);
  });

  it('切换模式与 k 上抛 update 事件', async () => {
    const wrapper = mountInput();
    // el-segmented 内部是 radio，直接触发组件 emit 语义
    wrapper.findComponent({ name: 'ElSegmented' }).vm.$emit('update:modelValue', 'direct');
    await flushPromises();
    expect(wrapper.emitted('update:mode')?.[0]).toEqual(['direct']);

    wrapper.findComponent({ name: 'ElSelect' }).vm.$emit('update:modelValue', '5');
    await flushPromises();
    expect(wrapper.emitted('update:k')?.[0]).toEqual([5]);
  });

  it('清空对话按钮上抛 clear', async () => {
    const wrapper = mountInput();
    await wrapper.get('[data-testid="clear-chat"]').trigger('click');
    expect(wrapper.emitted('clear')).toHaveLength(1);
  });
});

describe('检索过程面板（F08）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  const trace: TraceType = {
    question: '普通图书最多同时借阅几本借多久？',
    k: 3,
    chunkSize: 180,
    overlap: 30,
    rows: seedTrace('普通图书最多同时借阅几本借多久？', 3),
  };

  it('默认折叠，点击展开后显示候选表', async () => {
    const wrapper = mount(RetrievalTrace, {
      props: { trace },
      global: { plugins: [ElementPlus] },
    });
    expect(wrapper.find('table').exists()).toBe(false);

    await wrapper.get('.trace__toggle').trigger('click');
    expect(wrapper.find('table').exists()).toBe(true);
    expect(wrapper.text()).toContain('k=3');
    expect(wrapper.text()).toContain('片段 180 字');
  });

  it('区分采用与淘汰的片段', async () => {
    const wrapper = mount(RetrievalTrace, {
      props: { trace },
      global: { plugins: [ElementPlus] },
    });
    await wrapper.get('.trace__toggle').trigger('click');

    const kept = wrapper.findAll('[data-testid="trace-row-kept"]');
    const dropped = wrapper.findAll('[data-testid="trace-row-dropped"]');
    expect(kept).toHaveLength(3);
    expect(dropped.length).toBeGreaterThan(0);
    expect(kept[0]!.text()).toContain('采用');
    expect(dropped[0]!.text()).toContain('淘汰');
  });
});
