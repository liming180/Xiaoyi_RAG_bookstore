import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { knowledgeApi } from '@/api';
import { STATUS_POLL_INTERVAL } from '@/constants/app';
import type { IndexStatus, IndexStatusValue } from '@/types/api';

/**
 * 系统状态灯（F03）。
 *
 * 规格要求：Pinia 只放全局客户端状态，所以这里只存「知识库健康度」这一份跨页共享的客户端视图状态，
 * 不存业务数据（文档列表、消息列表都在各自页面组件里现取现用）。
 *
 * 三态：
 *   ready         → 绿灯「知识库已就绪」
 *   needs_rebuild → 黄灯「资料待更新」，可提问但提示基于旧库
 *   unavailable   → 红灯「知识库暂不可用」，仅直接模式可用
 */
export const useSystemStatusStore = defineStore('systemStatus', () => {
  const status = ref<IndexStatusValue>('unavailable');
  const detail = ref<IndexStatus | null>(null);
  const loading = ref(false);
  const lastError = ref<string | null>(null);
  const lastCheckedAt = ref<number | null>(null);
  const degradedBySse = ref(false);
  /**
   * 参数实验互斥（套餐 E3）：实验期间后端禁止提问（409）。
   *
   * 放在全局 store 而不是评测页局部状态，是因为要影响的地方有三处：
   * 全站横幅、对话页输入框禁用态、评测页创建按钮 —— 三处必须同时看到同一个值。
   */
  const experimentRunning = ref(false);

  let timer: ReturnType<typeof setInterval> | null = null;
  let inFlight = false;

  const isReady = computed(() => status.value === 'ready');
  const needsRebuild = computed(() => status.value === 'needs_rebuild');
  const unavailable = computed(() => status.value === 'unavailable');

  const label = computed(() => {
    if (degradedBySse.value) return 'AI 服务降级中';
    if (status.value === 'ready') return '知识库已就绪';
    if (status.value === 'needs_rebuild') return '资料待更新';
    return '知识库暂不可用';
  });

  const tone = computed<'ok' | 'warn' | 'error'>(() => {
    if (degradedBySse.value) return 'warn';
    if (status.value === 'ready') return 'ok';
    if (status.value === 'needs_rebuild') return 'warn';
    return 'error';
  });

  async function refresh(): Promise<void> {
    if (inFlight) return;
    inFlight = true;
    loading.value = true;
    try {
      const next = await knowledgeApi.fetchIndexStatus();
      detail.value = next;
      status.value = next.status;
      lastError.value = null;
      lastCheckedAt.value = Date.now();
    } catch (err) {
      status.value = 'unavailable';
      lastError.value = err instanceof Error ? err.message : String(err);
      lastCheckedAt.value = Date.now();
    } finally {
      loading.value = false;
      inFlight = false;
    }
  }

  /** 上传/删除/改参数后立刻置黄灯，不等下一次轮询 */
  function markNeedsRebuild(reason?: string): void {
    status.value = 'needs_rebuild';
    if (detail.value) {
      detail.value = { ...detail.value, status: 'needs_rebuild', reason: reason ?? '资料或分块设置已改变' };
    }
  }

  function markReady(chunkCount?: number): void {
    status.value = 'ready';
    if (detail.value) {
      detail.value = {
        ...detail.value,
        status: 'ready',
        reason: null,
        chunkCount: chunkCount ?? detail.value.chunkCount,
      };
    }
  }

  function setDegraded(flag: boolean): void {
    degradedBySse.value = flag;
  }

  function setExperimentRunning(flag: boolean): void {
    experimentRunning.value = flag;
  }

  /** 启动轮询；重复调用不会产生第二个定时器 */
  function startPolling(intervalMs = STATUS_POLL_INTERVAL): void {
    stopPolling();
    void refresh();
    timer = setInterval(() => void refresh(), intervalMs);
  }

  function stopPolling(): void {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  return {
    status,
    detail,
    loading,
    lastError,
    lastCheckedAt,
    degradedBySse,
    experimentRunning,
    isReady,
    needsRebuild,
    unavailable,
    label,
    tone,
    refresh,
    markNeedsRebuild,
    markReady,
    setDegraded,
    setExperimentRunning,
    startPolling,
    stopPolling,
  };
});
