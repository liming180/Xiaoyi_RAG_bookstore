import { computed, ref } from 'vue';
import type { AnswerMode, EvalCaseResult, EvalQuestion, EvalRun, EvalRunSummary, EvalStats } from '@/types/api';
import * as evalApi from '@/api/modules/eval';
import { ApiError } from '@/api';
import { EVAL_POLL_INTERVAL, K_DEFAULT } from '@/constants/app';
import { summarize } from './batch';

/**
 * 批量对照测试的状态机（F09）。
 *
 * 流程：选问题集 → POST /eval/batch → 轮询 GET /eval/runs/:id 直到 SUCCEEDED → 展示 cases。
 * 真实后端是异步跑，mock 是「首次 GET 时一次性生成」，所以这里必须真的轮询，
 * 不能假定 POST 回来就有结果 —— 否则接真后端时整段逻辑要重写。
 */
export function useBatchRun() {
  const questions = ref<EvalQuestion[]>([]);
  const selectedIds = ref<string[]>([]);
  const mode = ref<AnswerMode>('both');
  const k = ref<number>(K_DEFAULT);

  const run = ref<EvalRun | null>(null);
  const running = ref(false);
  const loading = ref(false);
  const error = ref<string | null>(null);

  const history = ref<EvalRunSummary[]>([]);
  const historyLoading = ref(false);
  const historyError = ref<string | null>(null);

  let timer: ReturnType<typeof setInterval> | null = null;

  const cases = computed<EvalCaseResult[]>(() => run.value?.cases ?? []);
  const stats = computed<EvalStats>(() => summarize(cases.value));
  const finished = computed(() => run.value?.status === 'SUCCEEDED' || run.value?.status === 'FAILED');

  function stopPolling(): void {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  async function loadQuestions(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      questions.value = await evalApi.listQuestions();
      // 默认全选：F09 的主路径就是「13 题全跑一遍」
      if (selectedIds.value.length === 0) {
        selectedIds.value = questions.value.map((q) => q.id);
      }
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : '题目加载失败';
    } finally {
      loading.value = false;
    }
  }

  function toggleQuestion(id: string): void {
    selectedIds.value = selectedIds.value.includes(id)
      ? selectedIds.value.filter((x) => x !== id)
      : [...selectedIds.value, id];
  }

  function selectAll(): void {
    selectedIds.value = questions.value.map((q) => q.id);
  }

  function selectNone(): void {
    selectedIds.value = [];
  }

  /** 轮询到终态为止。run 已 SUCCEEDED 时立刻停，不留悬挂定时器。 */
  function startPolling(id: string): void {
    stopPolling();
    timer = setInterval(() => {
      void poll(id);
    }, EVAL_POLL_INTERVAL);
  }

  async function poll(id: string): Promise<void> {
    try {
      const next = await evalApi.fetchBatchRun(id);
      run.value = next;
      if (next.status === 'SUCCEEDED' || next.status === 'FAILED') {
        stopPolling();
        running.value = false;
      }
    } catch (e) {
      stopPolling();
      running.value = false;
      error.value = e instanceof ApiError ? e.message : '评测轮询失败';
    }
  }

  async function start(): Promise<boolean> {
    if (running.value) return false;
    if (selectedIds.value.length === 0) {
      error.value = '请至少选择一道题';
      return false;
    }
    error.value = null;
    running.value = true;
    try {
      const created = await evalApi.startBatch({ questionIds: selectedIds.value, mode: mode.value, k: k.value });
      // 后端可能直接返回 SUCCEEDED（mock 就是这样），也可能返回 RUNNING；
      // 两种都要先拉一次详情，因为 POST 的响应里没有 cases。
      run.value = { ...created, cases: [] };
      await poll(created.id);
      if (!finished.value) startPolling(created.id);
      return true;
    } catch (e) {
      running.value = false;
      error.value = e instanceof ApiError ? e.message : '评测启动失败';
      return false;
    }
  }

  async function loadHistory(): Promise<void> {
    historyLoading.value = true;
    // 历史列表的错误单独存：它和「批量跑失败」是两件不同的事，
    // 共用一个 error 会让批量页签顶部冒出跟当前操作无关的红字。
    historyError.value = null;
    try {
      history.value = await evalApi.listRuns();
    } catch (e) {
      historyError.value = e instanceof ApiError ? e.message : '历史加载失败';
    } finally {
      historyLoading.value = false;
    }
  }

  async function openRun(id: string): Promise<void> {
    stopPolling();
    running.value = false;
    try {
      run.value = await evalApi.fetchBatchRun(id);
      if (!finished.value) {
        running.value = true;
        startPolling(id);
      }
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : '评测详情加载失败';
    }
  }

  function reset(): void {
    stopPolling();
    run.value = null;
    running.value = false;
    error.value = null;
  }

  return {
    questions,
    selectedIds,
    mode,
    k,
    run,
    running,
    loading,
    error,
    history,
    historyLoading,
    historyError,
    cases,
    stats,
    finished,
    loadQuestions,
    toggleQuestion,
    selectAll,
    selectNone,
    start,
    loadHistory,
    openRun,
    reset,
    stopPolling,
  };
}
