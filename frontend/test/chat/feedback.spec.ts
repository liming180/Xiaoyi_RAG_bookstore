import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus from 'element-plus';
import FeedbackBar from '@/features/chat/components/FeedbackBar.vue';
import { evalApi } from '@/api';
import { getState, resetState } from '@/mocks/state';
import type { Message } from '@/types/api';

/**
 * C1 反馈闭环前端部分。
 *
 * 覆盖：👍 直接提交、👎 展开标签、标签勾选后覆盖提交、
 * 失败回滚、禁用态、候选题池联动（服务端 mock 会落 candidate）。
 */
describe('反馈闭环（套餐 C1）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('点 👍 直接提交 up 并固化高亮', async () => {
    const spy = vi.spyOn(evalApi, 'submitFeedback').mockResolvedValue(undefined);
    const wrapper = mount(FeedbackBar, {
      props: { messageId: 'm-1' },
      global: { plugins: [ElementPlus] },
    });

    await wrapper.get('[data-testid="feedback-up"]').trigger('click');
    await flushPromises();

    expect(spy).toHaveBeenCalledWith('m-1', { rating: 'up', tags: undefined });
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['up']);
    expect(wrapper.get('[data-testid="feedback-up"]').classes()).toContain('fb__btn--active');
    spy.mockRestore();
  });

  it('点 👎 先展开原因标签，选中后覆盖提交', async () => {
    const spy = vi.spyOn(evalApi, 'submitFeedback').mockResolvedValue(undefined);
    const wrapper = mount(FeedbackBar, {
      props: { messageId: 'm-2' },
      global: { plugins: [ElementPlus] },
    });

    await wrapper.get('[data-testid="feedback-down"]').trigger('click');
    await flushPromises();
    expect(wrapper.find('[data-testid="feedback-tags"]').exists()).toBe(true);
    expect(spy).toHaveBeenCalledWith('m-2', { rating: 'down', tags: undefined });

    await wrapper.get('[data-testid="feedback-tag-wrong"]').trigger('click');
    await wrapper.get('[data-testid="feedback-tag-source"]').trigger('click');
    await wrapper.get('[data-testid="feedback-tag-confirm"]').trigger('click');
    await flushPromises();

    expect(spy).toHaveBeenLastCalledWith('m-2', { rating: 'down', tags: ['wrong', 'source'] });
    expect(wrapper.find('[data-testid="feedback-tags"]').exists()).toBe(false);
    spy.mockRestore();
  });

  it('提交失败回滚到上一态', async () => {
    vi.spyOn(evalApi, 'submitFeedback').mockRejectedValue(new Error('网络异常'));
    const wrapper = mount(FeedbackBar, {
      props: { messageId: 'm-3', modelValue: 'down' },
      global: { plugins: [ElementPlus] },
    });

    await wrapper.get('[data-testid="feedback-up"]').trigger('click');
    await flushPromises();

    // 回滚到 down
    expect(wrapper.get('[data-testid="feedback-down"]').classes()).toContain('fb__btn--active');
    expect(wrapper.get('[data-testid="feedback-up"]').classes()).not.toContain('fb__btn--active');
    expect(wrapper.emitted('update:modelValue')).toBeUndefined();
    vi.restoreAllMocks();
  });

  it('禁用态不提交', async () => {
    const spy = vi.spyOn(evalApi, 'submitFeedback').mockResolvedValue(undefined);
    const wrapper = mount(FeedbackBar, {
      props: { messageId: 'm-4', disabled: true },
      global: { plugins: [ElementPlus] },
    });
    expect(wrapper.get('[data-testid="feedback-up"]').attributes('disabled')).toBeDefined();
    await wrapper.get('[data-testid="feedback-down"]').trigger('click');
    await flushPromises();
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it('👎 落库后候选池出现该问题（端到端走 MSW）', async () => {
    // 先制造一条真实消息
    const { chatApi } = await import('@/api');
    await chatApi.clearMessages('c-demo');
    for await (const _ev of chatApi.streamAnswer({
      conversationId: 'c-demo',
      question: '讨论空间怎么预约？',
      mode: 'rag',
      k: 3,
    })) {
      void _ev;
    }
    const list = await chatApi.listMessages('c-demo');
    const assistant = list.find((m: Message) => m.role === 'assistant');
    expect(assistant).toBeTruthy();

    const before = (await evalApi.listCandidates()).length;
    await evalApi.submitFeedback(assistant!.id, { rating: 'down', tags: ['wrong'] });
    const after = await evalApi.listCandidates();

    expect(after.length).toBe(before + 1);
    expect(after[0]!.source).toBe('feedback');
    expect(after[0]!.status).toBe('pending');
    expect(getState().feedback[assistant!.id]).toBe('down');
  });

  it('重复反馈只保留最新（同消息覆盖）', async () => {
    const { chatApi } = await import('@/api');
    await chatApi.clearMessages('c-demo');
    for await (const _ev of chatApi.streamAnswer({
      conversationId: 'c-demo',
      question: '读书会什么时候举行？',
      mode: 'rag',
      k: 3,
    })) {
      void _ev;
    }
    const list = await chatApi.listMessages('c-demo');
    const assistant = list.find((m: Message) => m.role === 'assistant');

    await evalApi.submitFeedback(assistant!.id, { rating: 'down' });
    await evalApi.submitFeedback(assistant!.id, { rating: 'up' });

    expect(getState().feedback[assistant!.id]).toBe('up');
    const summary = await evalApi.fetchFeedbackSummary();
    expect(summary.up).toBeGreaterThanOrEqual(1);
  });
});
