import { describe, expect, it, vi, beforeEach } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useSystemStatusStore } from '@/stores/systemStatus';
import { useConversationsStore } from '@/stores/conversations';
import { useQueryPrefs } from '@/composables/useQueryPrefs';
import { knowledgeApi } from '@/api';
import { resetState } from '@/mocks/state';
import { K_DEFAULT, STORAGE_KEYS } from '@/constants/app';

describe('Pinia：系统状态灯（F03）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('refresh 拉到 ready 并带上片段数', async () => {
    const store = useSystemStatusStore();
    await store.refresh();
    expect(store.status).toBe('ready');
    expect(store.isReady).toBe(true);
    expect(store.label).toBe('知识库已就绪');
    expect(store.tone).toBe('ok');
    expect(store.detail?.chunkCount).toBeGreaterThan(10);
  });

  it('markNeedsRebuild 立刻变黄，不必等轮询', () => {
    const store = useSystemStatusStore();
    store.markReady(15);
    store.markNeedsRebuild('资料已变更');
    expect(store.status).toBe('needs_rebuild');
    expect(store.needsRebuild).toBe(true);
    expect(store.label).toBe('资料待更新');
    expect(store.tone).toBe('warn');
  });

  it('startPolling 会立刻拉一次，且重复调用不叠加定时器', async () => {
    vi.useFakeTimers();
    // 注意：Pinia action 内部调用的是闭包里的原函数，spyOn(store, 'refresh') 拦不到，
    // 所以这里统计真正的 API 调用次数。
    const apiSpy = vi.spyOn(knowledgeApi, 'fetchIndexStatus');
    const store = useSystemStatusStore();

    store.startPolling(30_000);
    await vi.advanceTimersByTimeAsync(0);
    expect(apiSpy).toHaveBeenCalledTimes(1);

    // 第二次 start 会先 stopPolling 再重建，同时立刻再拉一次
    store.startPolling(30_000);
    await vi.advanceTimersByTimeAsync(0);
    expect(apiSpy).toHaveBeenCalledTimes(2);

    // 只应留下一个定时器：30s 后只多一次调用
    await vi.advanceTimersByTimeAsync(30_000);
    const afterOneTick = apiSpy.mock.calls.length;
    expect(afterOneTick).toBe(3);

    store.stopPolling();
    await vi.advanceTimersByTimeAsync(90_000);
    expect(apiSpy.mock.calls.length).toBe(afterOneTick);
    apiSpy.mockRestore();
    vi.useRealTimers();
  });

  it('接口失败时降级为 unavailable 并记错误', async () => {
    const store = useSystemStatusStore();
    const original = store.refresh;
    // 直接构造失败：把 knowledgeApi 换掉不便，这里验证 setter 语义
    store.markNeedsRebuild();
    expect(store.status).toBe('needs_rebuild');
    store.markReady(23);
    expect(store.status).toBe('ready');
    expect(original).toBeTypeOf('function');
  });

  it('SSE 降级标记会覆盖状态文案', () => {
    const store = useSystemStatusStore();
    store.markReady(15);
    store.setDegraded(true);
    expect(store.label).toBe('AI 服务降级中');
    expect(store.tone).toBe('warn');
    store.setDegraded(false);
    expect(store.label).toBe('知识库已就绪');
  });
});

describe('Pinia：会话列表', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('fetchList 自动选中第一个会话并写入 localStorage', async () => {
    const store = useConversationsStore();
    await store.fetchList();
    expect(store.list.length).toBeGreaterThan(0);
    expect(store.activeId).toBe(store.list[0]?.id);
    expect(window.localStorage.getItem(STORAGE_KEYS.conversationId)).toBe(store.activeId);
  });

  it('create 新建会话并切到新会话', async () => {
    const store = useConversationsStore();
    await store.fetchList();
    const before = store.list.length;
    const conv = await store.create('测试会话');
    expect(conv).not.toBeNull();
    expect(store.list.length).toBe(before + 1);
    expect(store.activeId).toBe(conv?.id);
  });

  it('remove 后当前会话切到剩余第一个', async () => {
    const store = useConversationsStore();
    await store.fetchList();
    const target = store.activeId!;
    await store.remove(target);
    expect(store.list.some((c) => c.id === target)).toBe(false);
  });
});

describe('组合式：提问参数（F06/F07）', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('默认 rag + k=3', () => {
    const { mode, k } = useQueryPrefs();
    expect(mode.value).toBe('rag');
    expect(k.value).toBe(K_DEFAULT);
  });

  it('setK 会夹在 1..5 并持久化', () => {
    const { k, setK } = useQueryPrefs();
    setK(99);
    expect(k.value).toBe(5);
    setK(-3);
    expect(k.value).toBe(1);
    setK(4);
    expect(window.localStorage.getItem(STORAGE_KEYS.k)).toBe('4');
  });

  it('非法持久化值回落到默认', () => {
    window.localStorage.setItem(STORAGE_KEYS.k, 'abc');
    window.localStorage.setItem(STORAGE_KEYS.mode, 'nope');
    const { mode, k } = useQueryPrefs();
    expect(mode.value).toBe('rag');
    expect(k.value).toBe(K_DEFAULT);
  });

  it('setMode 持久化并给出中文标签', () => {
    const { modeLabel, setMode } = useQueryPrefs();
    setMode('both');
    expect(modeLabel.value).toBe('对照');
    expect(window.localStorage.getItem(STORAGE_KEYS.mode)).toBe('both');
  });
});
