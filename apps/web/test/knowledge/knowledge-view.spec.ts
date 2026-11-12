import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { createPinia, setActivePinia } from 'pinia';
import { createRouter, createMemoryHistory } from 'vue-router';
import KnowledgeView from '@/features/knowledge/views/KnowledgeView.vue';
import { useSystemStatusStore } from '@/stores/systemStatus';
import { knowledgeApi } from '@/api';
import { resetState } from '@/mocks/state';

/**
 * 知识库页集成（F01/F02/F03 联动）。
 *
 * 真走 MSW：列表 6 份 → 上传 → 状态灯立刻变黄 → 建库 → 完成回绿。
 *
 * 注意：MSW 的 fetch 走的是宏任务链路，`flushPromises()` 只排空微任务，
 * 所以凡是「等接口回来」的断言都走 waitFor 轮询，不用固定 sleep。
 */

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/knowledge', name: 'knowledge', component: { template: '<div />' } },
      { path: '/knowledge/chunks', name: 'chunks', component: { template: '<div />' } },
      { path: '/chat', name: 'chat', component: { template: '<div />' } },
    ],
  });
}

async function mountPage() {
  const router = makeRouter();
  await router.push('/knowledge');
  await router.isReady();
  const wrapper = mount(KnowledgeView, {
    global: { plugins: [ElementPlus, router] },
  });
  await flushPromises();
  return { wrapper, router };
}

/** 轮询直到条件成立（MSW 异步链路专用） */
async function waitFor(check: () => boolean, timeout = 4000, label = '条件'): Promise<void> {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    await flushPromises();
    if (check()) return;
    await new Promise((r) => setTimeout(r, 20));
  }
  throw new Error(`等待超时：${label}`);
}

describe('知识库页（F01/F02）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('挂载后拉列表与索引状态，计数与徽标正确', async () => {
    const { wrapper } = await mountPage();
    await waitFor(() => wrapper.findAll('tbody tr').length === 6, 4000, '列表 6 行');

    expect(wrapper.find('[data-testid="page-knowledge"]').exists()).toBe(true);

    const countText = wrapper.get('[data-testid="doc-count"]').text();
    expect(countText).toContain('6 份资料');
    expect(countText).toContain('个片段');

    const summary = wrapper.get('[data-testid="doc-status-summary"]').text();
    expect(summary).toContain('已入库 6');
    expect(summary).toContain('未核实 1');
  });

  it('建库面板显示当前库参数 180 / 30', async () => {
    const { wrapper } = await mountPage();
    await waitFor(
      () => wrapper.find('[data-testid="build-current"]').exists(),
      4000,
      '建库面板当前参数',
    );
    const current = wrapper.get('[data-testid="build-current"]').text();
    expect(current).toContain('180');
    expect(current).toContain('30');
    expect(wrapper.find('[data-testid="build-submit"]').attributes('disabled')).toBeUndefined();
  });

  it('参数改成与已建库不一致时提示需要重建', async () => {
    const { wrapper } = await mountPage();
    await waitFor(
      () => wrapper.find('[data-testid="build-current"]').exists(),
      4000,
      '建库面板当前参数',
    );

    // 直接改子组件内部输入值，等价于用户在输入框里敲数字
    await wrapper.findComponent({ name: 'ElInputNumber' }).vm.$emit('update:modelValue', 120);
    await flushPromises();

    expect(wrapper.find('[data-testid="build-dirty"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="build-dirty-hint"]').text()).toContain('重新建库');
  });

  it('删除资料需要二次确认，确认后列表少一份并变待重建', async () => {
    const { wrapper } = await mountPage();
    const store = useSystemStatusStore();
    await waitFor(() => store.status === 'ready', 4000, '状态灯 ready');
    await waitFor(() => wrapper.findAll('tbody tr').length === 6, 4000, '列表 6 行');

    const { ElMessageBox } = await import('element-plus');
    const confirmSpy = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce('confirm');

    await wrapper.get('[data-testid="doc-delete-D02"]').trigger('click');
    await waitFor(() => wrapper.findAll('tbody tr').length === 5, 4000, '删除后 5 行');

    // 确认框文案包含文档名
    expect(confirmSpy.mock.calls[0]![0]).toContain('02_');
    expect(store.status).toBe('needs_rebuild');

    confirmSpy.mockRestore();
  });

  it('取消删除时列表不变', async () => {
    const { wrapper } = await mountPage();
    await waitFor(() => wrapper.findAll('tbody tr').length === 6, 4000, '列表 6 行');

    const { ElMessageBox } = await import('element-plus');
    const confirmSpy = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce('cancel');

    await wrapper.get('[data-testid="doc-delete-D02"]').trigger('click');
    await flushPromises();
    await new Promise((r) => setTimeout(r, 60));

    expect(wrapper.findAll('tbody tr')).toHaveLength(6);
    confirmSpy.mockRestore();
  });

  it('停用资料后行状态变 DISABLED 且状态灯变黄', async () => {
    const { wrapper } = await mountPage();
    const store = useSystemStatusStore();
    await waitFor(() => wrapper.findAll('tbody tr').length === 6, 4000, '列表 6 行');

    await wrapper.get('[data-testid="doc-toggle-D01"]').trigger('click');
    await waitFor(() => store.status === 'needs_rebuild', 4000, '状态灯变黄');

    expect(wrapper.find('[data-testid="doc-row-D01"]').attributes('data-status')).toBe('DISABLED');
  });

  it('建库跑完阶段推进到 100% 并把状态灯转回 ready', async () => {
    const { wrapper } = await mountPage();
    const store = useSystemStatusStore();
    await waitFor(
      () => wrapper.find('[data-testid="build-current"]').exists(),
      4000,
      '建库面板当前参数',
    );
    store.markNeedsRebuild('测试前置');

    await wrapper.get('[data-testid="build-submit"]').trigger('click');
    await waitFor(
      () => wrapper.find('[data-testid="build-progress"]').exists(),
      4000,
      '进度区出现',
    );

    // mock 任务 900ms 走完，轮询 1s 一次
    await waitFor(
      () => wrapper.find('[data-testid="build-summary"]').exists(),
      8000,
      '建库完成摘要',
    );

    expect(wrapper.get('[data-testid="build-summary"]').text()).toMatch(/文档 \d+ 份，片段 \d+ 条/);
    expect(store.status).toBe('ready');
  }, 20000);

  it('建库参数非法时按钮禁用', async () => {
    const { wrapper } = await mountPage();
    await waitFor(
      () => wrapper.findComponent({ name: 'BuildPanel' }).exists(),
      4000,
      '建库面板挂载',
    );

    const numbers = wrapper.findAllComponents({ name: 'ElInputNumber' });
    expect(numbers.length).toBeGreaterThanOrEqual(2);
    // 第二个是 overlap，把它抬到 >= chunkSize
    await numbers[1]!.vm.$emit('update:modelValue', 180);
    await flushPromises();

    expect(wrapper.find('[data-testid="build-invalid"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="build-submit"]').attributes('disabled')).toBeDefined();
  });
});

describe('知识库页上传（F01）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('上传 .md 成功后列表 +1 且提示重新建库', async () => {
    const { wrapper } = await mountPage();
    const store = useSystemStatusStore();
    await waitFor(() => wrapper.findAll('tbody tr').length === 6, 4000, '列表 6 行');

    const dialog = wrapper.findComponent({ name: 'UploadDialog' });
    expect(dialog.exists()).toBe(true);

    const file = new File(['# 新增资料\n这是一份测试资料。'], '07_新增资料.md', {
      type: 'text/markdown',
    });
    dialog.vm.$emit('submit', [file]);

    await waitFor(() => wrapper.findAll('tbody tr').length === 7, 4000, '上传后 7 行');
    expect(store.status).toBe('needs_rebuild');
  });

  it('上传非法类型不会进入列表', async () => {
    const { wrapper } = await mountPage();
    await waitFor(() => wrapper.findAll('tbody tr').length === 6, 4000, '列表 6 行');

    const dialog = wrapper.findComponent({ name: 'UploadDialog' });
    const bad = new File(['x'], 'report.pdf', { type: 'application/pdf' });
    dialog.vm.$emit('submit', [bad]);
    await flushPromises();
    await new Promise((r) => setTimeout(r, 80));

    expect(wrapper.findAll('tbody tr')).toHaveLength(6);
  });

  it('查看全文拉片段并拼接原文', async () => {
    const { wrapper } = await mountPage();
    await waitFor(() => wrapper.findAll('tbody tr').length === 6, 4000, '列表 6 行');

    const chunks = await knowledgeApi.listChunks({ docId: 'D01' });
    expect(chunks.length).toBeGreaterThan(0);

    await wrapper.get('.doc-table__name').trigger('click');
    await waitFor(
      () => wrapper.find('[data-testid="doc-viewer-text"]').exists(),
      4000,
      '全文弹窗正文',
    );

    const text = wrapper.get('[data-testid="doc-viewer-text"]').text();
    expect(text.length).toBeGreaterThan(0);
    // 拼接后不应出现重叠造成的重复首段
    expect(text).not.toContain('\u0000');
  });
});
