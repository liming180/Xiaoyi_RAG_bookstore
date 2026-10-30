import { computed, ref } from 'vue';
import type { Experiment, ExperimentAxis, ExperimentReport, ExperimentRun } from '@/types/api';
import * as evalApi from '@/api/modules/eval';
import { ApiError, emit } from '@/api';
import { EVAL_POLL_INTERVAL } from '@/constants/app';
import { defaultAxes, expandAxes, pickBestRun } from './experiment';

/**
 * 参数实验状态机（套餐 E3）。
 *
 * 互斥语义：实验期间后端禁止提问（`POST /chat/stream` 返回 409）。
 * 前端不只是显示横幅，还要把这件事广播给全局 —— 通过 `emit('experiment:running')`
 * 让 AppShell 的横幅与 ChatInput 的禁用态都能响应，避免各页面各写一套判断。
 */
export function useExperiment() {
  const axes = ref<ExperimentAxis>(defaultAxes());
  const name = ref('参数矩阵实验');

  const experiment = ref<Experiment | null>(null);
  const runs = ref<ExperimentRun[]>([]);
  const creating = ref(false);
  const polling = ref(false);
  const error = ref<string | null>(null);
  /** 409 互斥：另一个实验正在跑 */
  const conflict = ref<string | null>(null);

  let timer: ReturnType<typeof setInterval> | null = null;

  const groupCount = computed(() => expandAxes(axes.value).length);
  const best = computed(() => pickBestRun(runs.value));
  const progress = computed(() => experiment.value?.progress ?? 0);
  const isRunning = computed(() => experiment.value?.status === 'RUNNING');
  const isDone = computed(() => experiment.value?.status === 'SUCCEEDED');
  const hasReport = computed(() => runs.value.length > 0);

  function stopPolling(): void {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
    polling.value = false;
  }

  async function loadReport(id: string): Promise<void> {
    const report: ExperimentReport = await evalApi.fetchExperimentReport(id);
    runs.value = report.runs;
    experiment.value = report.experiment;
  }

  async function poll(id: string): Promise<void> {
    try {
      const next = await evalApi.fetchExperiment(id);
      experiment.value = next;
      if (next.status !== 'RUNNING') {
        stopPolling();
        emit('experiment:running', false);
        await loadReport(id);
      }
    } catch (e) {
      stopPolling();
      emit('experiment:running', false);
      error.value = e instanceof ApiError ? e.message : '实验状态查询失败';
    }
  }

  function startPolling(id: string): void {
    stopPolling();
    polling.value = true;
    timer = setInterval(() => {
      void poll(id);
    }, EVAL_POLL_INTERVAL);
  }

  async function create(): Promise<boolean> {
    if (creating.value) return false;
    conflict.value = null;
    error.value = null;
    if (groupCount.value === 0) {
      error.value = '参数矩阵为空，请至少各留一个取值';
      return false;
    }
    creating.value = true;
    try {
      const exp = await evalApi.createExperiment({ name: name.value.trim() || '参数矩阵实验', axes: axes.value });
      experiment.value = exp;
      runs.value = [];
      emit('experiment:running', true);
      if (exp.status === 'RUNNING') {
        startPolling(exp.id);
      } else {
        await loadReport(exp.id);
      }
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.httpStatus === 409) {
        // 409 是「已有实验在执行」，不是失败 —— 单独放一个字段，
        // 页面上显示成提示而不是红字错误。
        conflict.value = e.message || '已有实验在执行，请等待完成';
      } else {
        error.value = e instanceof ApiError ? e.message : '实验创建失败';
      }
      return false;
    } finally {
      creating.value = false;
    }
  }

  /** 勾选/取消某个取值；数组空了就补回默认值，避免用户把自己锁死在「矩阵为空」 */
  function toggleAxisValue<K extends keyof ExperimentAxis>(key: K, value: ExperimentAxis[K][number]): void {
    const list = axes.value[key] as Array<ExperimentAxis[K][number]>;
    const idx = list.indexOf(value);
    if (idx >= 0) {
      if (list.length === 1) return; // 至少保留一个取值
      list.splice(idx, 1);
    } else {
      list.push(value);
      list.sort((a, b) => (typeof a === 'number' && typeof b === 'number' ? a - b : Number(a) - Number(b)));
    }
  }

  function hasAxisValue<K extends keyof ExperimentAxis>(key: K, value: ExperimentAxis[K][number]): boolean {
    return (axes.value[key] as Array<ExperimentAxis[K][number]>).includes(value);
  }

  function reset(): void {
    stopPolling();
    emit('experiment:running', false);
    experiment.value = null;
    runs.value = [];
    error.value = null;
    conflict.value = null;
  }

  return {
    axes,
    name,
    experiment,
    runs,
    creating,
    polling,
    error,
    conflict,
    groupCount,
    best,
    progress,
    isRunning,
    isDone,
    hasReport,
    create,
    toggleAxisValue,
    hasAxisValue,
    stopPolling,
    reset,
  };
}
