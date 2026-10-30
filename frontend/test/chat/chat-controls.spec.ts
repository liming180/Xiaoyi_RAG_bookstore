import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus from 'element-plus';
import SuggestionChips from '@/features/chat/components/SuggestionChips.vue';
import ComparePane from '@/features/chat/components/ComparePane.vue';
import ClearChatButton from '@/features/chat/components/ClearChatButton.vue';
import type { Message } from '@/types/api';
import { seedCitations } from '@/mocks/data';
import { resetState } from '@/mocks/state';

function assistant(content: string, over: Partial<Message> = {}): Message {
  return {
    id: 'm-1',
    conversationId: 'c-demo',
    role: 'assistant',
    content,
    createdAt: Date.now(),
    citations: [],
    trace: null,
    usage: null,
    elapsedMs: 1200,
    degraded: false,
    suggestions: [],
    feedback: null,
    ...over,
  };
}

describe('示例问题 chips（F04）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('渲染全部示例并上抛点击', async () => {
    const wrapper = mount(SuggestionChips, {
      props: { items: ['读书会什么时候举行？', '普通图书最多能借几本？'] },
      global: { plugins: [ElementPlus] },
    });
    const chips = wrapper.findAll('.sugg__chip');
    expect(chips).toHaveLength(2);
    await chips[1]!.trigger('click');
    expect(wrapper.emitted('pick')?.[0]).toEqual(['普通图书最多能借几本？']);
  });

  it('空列表不渲染', () => {
    const wrapper = mount(SuggestionChips, {
      props: { items: [] },
      global: { plugins: [ElementPlus] },
    });
    expect(wrapper.find('[data-testid="suggestion-chips"]').exists()).toBe(false);
  });

  it('禁用时点击不上抛', async () => {
    const wrapper = mount(SuggestionChips, {
      props: { items: ['问题'], disabled: true },
      global: { plugins: [ElementPlus] },
    });
    const chip = wrapper.get('.sugg__chip');
    expect(chip.attributes('disabled')).toBeDefined();
    await chip.trigger('click');
    expect(wrapper.emitted('pick')).toBeUndefined();
  });
});

describe('对照模式两栏（F06）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('左栏带引用徽标，右栏为纯文本', async () => {
    const wrapper = mount(ComparePane, {
      props: {
        rag: assistant('最多借 4 本 [1]。', { citations: seedCitations(1) }),
        direct: assistant('一般可借 5 本。', { degraded: true, id: 'm-2' }),
      },
      global: { plugins: [ElementPlus] },
    });

    const rag = wrapper.get('[data-testid="compare-rag"]');
    const direct = wrapper.get('[data-testid="compare-direct"]');
    expect(rag.text()).toContain('引用知识库');
    expect(rag.find('[data-testid="cite-badge"]').exists()).toBe(true);
    expect(direct.text()).toContain('不查资料');
    expect(direct.text()).toContain('一般可借 5 本。');
  });

  it('rag 侧流式中显示检索占位', () => {
    const wrapper = mount(ComparePane, {
      props: { rag: null, direct: null, ragPending: true },
      global: { plugins: [ElementPlus] },
    });
    expect(wrapper.get('[data-testid="compare-rag"]').text()).toContain('正在检索');
    expect(wrapper.get('[data-testid="compare-direct"]').text()).toContain('暂无结果');
  });

  it('优先展示流式草稿正文', () => {
    const wrapper = mount(ComparePane, {
      props: { rag: null, direct: null, ragDraft: '正在生成的片段', directDraft: '直答草稿' },
      global: { plugins: [ElementPlus] },
    });
    expect(wrapper.text()).toContain('正在生成的片段');
    expect(wrapper.text()).toContain('直答草稿');
  });
});

describe('清空对话确认（F10）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('确认后上抛 confirm，取消则不上抛', async () => {
    const wrapper = mount(ClearChatButton, { global: { plugins: [ElementPlus] } });

    // 取消
    const box = wrapper.vm.$el as HTMLElement;
    expect(box.textContent).toContain('清空对话');

    // 直接调用组件内部逻辑不方便，改用 ElMessageBox mock 断言两条分支
    const { ElMessageBox } = await import('element-plus');
    const confirmSpy = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockRejectedValueOnce('cancel')
      .mockResolvedValueOnce('confirm' as never);

    await wrapper.get('[data-testid="clear-chat"]').trigger('click');
    await flushPromises();
    expect(wrapper.emitted('confirm')).toBeUndefined();

    await wrapper.get('[data-testid="clear-chat"]').trigger('click');
    await flushPromises();
    expect(wrapper.emitted('confirm')).toHaveLength(1);
    expect(confirmSpy).toHaveBeenCalledTimes(2);
    confirmSpy.mockRestore();
  });

  it('禁用时不弹确认', async () => {
    const wrapper = mount(ClearChatButton, {
      props: { disabled: true },
      global: { plugins: [ElementPlus] },
    });
    expect(wrapper.get('[data-testid="clear-chat"]').attributes('disabled')).toBeDefined();
  });
});
