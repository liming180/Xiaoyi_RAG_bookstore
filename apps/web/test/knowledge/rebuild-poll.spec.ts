import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, nextTick } from 'vue';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { knowledgeApi } from '@/api';
import { useRebuild } from '@/features/knowledge/composables/useRebuild';
import { INDEX_TASK_POLL_INTERVAL } from '@/constants/app';
import type { IndexTask } from '@/types/api';
import { resetState } from '@/mocks/state';

/**
 * 建库轮询（F02）。
 *
 * 两道硬约束都在这里钉住：
 *  1. 见到终态立刻停表，不再打接口；
 *  2. 组件卸载停表 —— 页面切走后不许留定时器。
 */

function task(over: Partial<IndexTask> = {}): IndexTask {
  return {
    id: 'task-1',
    status: 'RUNNING',
    stage: 'parsing',
    progress: 10,
    chunkSize: 180,
    overlap: 30,
    docCount: 6,
    chunkCount: 0,
    error: null,
    startedAt: 0,
    finishedAt: null,
    ...over,
  };
}

/** 把 composable 挂进真实组件，才能验证 onBeforeUnmount */
function mountRebuild() {
  let api!: ReturnType<typeof useRebuild>;
  const Host = defineComponent({
    setup() {
      api = useRebuild();
      return () => h('div');
    },
  });
  const wrapper = mount(Host);
  return { wrapper, api };
}

describe('建库轮询（F02）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
    vi.useRealTimers();
  });

  it('推进到终态后停表，不再继续打接口', async () => {
    vi.useFakeTimers();
    const { api } = mountRebuild();

    const created = task({ id: 'task-run', status: 'RUNNING', stage: 'parsing' });
    vi.spyOn(knowledgeApi, 'rebuildIndex').mockResolvedValueOnce(created);

    const running = vi
      .spyOn(knowledgeApi, 'fetchIndexTask')
      .mockResolvedValueOnce(task({ id: 'task-run', status: 'RUNNING', progress: 40, stage: 'splitting' }))
      .mockResolvedValueOnce(
        task({ id: 'task-run', status: 'SUCCEEDED', stage: 'done', progress: 100, chunkCount: 15 }),
      );

    await api.rebuild({ chunkSize: 180, overlap: 30 });
    expect(api.running.value).toBe(true);
    expect(api.polling.value).toBe(true);

    // 第 1 次轮询：仍在跑
    await vi.advanceTimersByTimeAsync(INDEX_TASK_POLL_INTERVAL);
    expect(running).toHaveBeenCalledTimes(1);
    expect(api.running.value).toBe(true);
    expect(api.percent.value).toBe(40);
    expect(api.stage.value).toBe('切分片段');

    // 第 2 次轮询：终态 → 停表
    await vi.advanceTimersByTimeAsync(INDEX_TASK_POLL_INTERVAL);
    expect(running).toHaveBeenCalledTimes(2);
    expect(api.running.value).toBe(false);
    expect(api.polling.value).toBe(false);
    expect(api.finished.value).toBe(true);
    expect(api.percent.value).toBe(100);

    // 再等三个周期，确认没有继续打接口
    await vi.advanceTimersByTimeAsync(INDEX_TASK_POLL_INTERVAL * 3);
    expect(running).toHaveBeenCalledTimes(2);

    vi.useRealTimers();
  });

  it('组件卸载时停表（无泄漏）', async () => {
    vi.useFakeTimers();
    const { wrapper, api } = mountRebuild();

    vi.spyOn(knowledgeApi, 'rebuildIndex').mockResolvedValueOnce(task({ id: 'task-leak' }));
    const running = vi
      .spyOn(knowledgeApi, 'fetchIndexTask')
      .mockResolvedValue(task({ id: 'task-leak', status: 'RUNNING', progress: 30 }));

    await api.rebuild({ chunkSize: 180, overlap: 30 });
    await vi.advanceTimersByTimeAsync(INDEX_TASK_POLL_INTERVAL);
    expect(running).toHaveBeenCalledTimes(1);

    wrapper.unmount();
    await nextTick();
    await vi.advanceTimersByTimeAsync(INDEX_TASK_POLL_INTERVAL * 5);

    // 卸载后再等 5 个周期，调用次数不再增长
    expect(running).toHaveBeenCalledTimes(1);
    expect(api.polling.value).toBe(false);

    vi.useRealTimers();
  });

  it('失败态停表并暴露 failed', async () => {
    vi.useFakeTimers();
    const { api } = mountRebuild();

    vi.spyOn(knowledgeApi, 'rebuildIndex').mockResolvedValueOnce(task({ id: 'task-bad' }));
    const running = vi
      .spyOn(knowledgeApi, 'fetchIndexTask')
      .mockResolvedValueOnce(
        task({ id: 'task-bad', status: 'FAILED', stage: 'embedding', progress: 55, error: '向量服务超时' }),
      );

    await api.rebuild({ chunkSize: 180, overlap: 30 });
    await vi.advanceTimersByTimeAsync(INDEX_TASK_POLL_INTERVAL);

    expect(api.failed.value).toBe(true);
    expect(api.running.value).toBe(false);
    expect(api.task.value?.error).toBe('向量服务超时');

    await vi.advanceTimersByTimeAsync(INDEX_TASK_POLL_INTERVAL * 3);
    expect(running).toHaveBeenCalledTimes(1);

    vi.useRealTimers();
  });

  it('参数非法时 POST 直接失败，进入错误态', async () => {
    const { api } = mountRebuild();
    // MSW 会对 overlap >= chunkSize 返回 40003
    const ok = await api.rebuild({ chunkSize: 100, overlap: 100 });
    expect(ok).toBe(false);
    expect(api.error.value).toContain('重叠字数');
    expect(api.running.value).toBe(false);
  });

  it('重复点击不会并发开两套轮询', async () => {
    vi.useFakeTimers();
    const { api } = mountRebuild();

    vi.spyOn(knowledgeApi, 'rebuildIndex').mockResolvedValue(task({ id: 'task-dup' }));
    const running = vi
      .spyOn(knowledgeApi, 'fetchIndexTask')
      .mockResolvedValue(task({ id: 'task-dup', status: 'RUNNING', progress: 20 }));

    await api.rebuild({ chunkSize: 180, overlap: 30 });
    const second = await api.rebuild({ chunkSize: 120, overlap: 20 });
    expect(second).toBe(false);

    await vi.advanceTimersByTimeAsync(INDEX_TASK_POLL_INTERVAL);
    expect(running).toHaveBeenCalledTimes(1);

    api.stopPolling();
    vi.useRealTimers();
  });
});
