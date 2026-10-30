import { computed, onBeforeUnmount, ref } from 'vue';
import { knowledgeApi } from '@/api';
import { INDEX_TASK_POLL_INTERVAL } from '@/constants/app';
import type { IndexTask } from '@/types/api';
import { isTerminal, progressPercent, stageLabel } from './buildParams';

/**
 * 建库任务轮询（F02）。
 *
 * 关键约束：轮询必须在组件卸载时停表 —— 否则页面切走后定时器还在打接口，
 * vitest 里表现为「测试结束了还有 pending timer」，真机上表现为无意义请求。
 */
export function useRebuild() {
  const task = ref<IndexTask | null>(null);
  const running = ref(false);
  const error = ref<string | null>(null);
  const polling = ref(false);

  let timer: ReturnType<typeof setInterval> | null = null;

  const percent = computed(() => progressPercent(task.value));
  const stage = computed(() => stageLabel(task.value));
  const finished = computed(() => task.value?.status === 'SUCCEEDED');
  const failed = computed(() => task.value?.status === 'FAILED');

  function stopPolling(): void {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
    polling.value = false;
  }

  /** 单次拉取；终态时自动停表 */
  async function poll(taskId: string): Promise<void> {
    try {
      const next = await knowledgeApi.fetchIndexTask(taskId);
      task.value = next;
      if (isTerminal(next)) {
        stopPolling();
        running.value = false;
      }
    } catch (e) {
      stopPolling();
      running.value = false;
      error.value = e instanceof Error ? e.message : '建库进度获取失败';
    }
  }

  function startPolling(taskId: string, intervalMs = INDEX_TASK_POLL_INTERVAL): void {
    stopPolling();
    polling.value = true;
    timer = setInterval(() => void poll(taskId), intervalMs);
  }

  /** 发起重建：POST 拿任务 → 立刻拉一次 → 开轮询 */
  async function rebuild(params: { chunkSize: number; overlap: number }): Promise<boolean> {
    if (running.value) return false;
    running.value = true;
    error.value = null;
    try {
      const created = await knowledgeApi.rebuildIndex(params);
      task.value = created;
      if (isTerminal(created)) {
        running.value = false;
        return true;
      }
      startPolling(created.id);
      return true;
    } catch (e) {
      running.value = false;
      error.value = e instanceof Error ? e.message : '建库请求失败';
      return false;
    }
  }

  /** 手动拉一次（页面切回来时补状态用） */
  async function refresh(taskId: string): Promise<void> {
    await poll(taskId);
  }

  function reset(): void {
    stopPolling();
    task.value = null;
    running.value = false;
    error.value = null;
  }

  onBeforeUnmount(() => {
    stopPolling();
  });

  return {
    task,
    running,
    polling,
    error,
    percent,
    stage,
    finished,
    failed,
    rebuild,
    refresh,
    reset,
    stopPolling,
  };
}
