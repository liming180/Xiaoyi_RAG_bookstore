<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import type { AnswerMode, EvalCandidate, FeedbackSummary } from '@/types/api';
import { evalApi } from '@/api';
import { ApiError } from '@/api';
import BatchRunner from '../components/BatchRunner.vue';
import RunHistory from '../components/RunHistory.vue';
import CandidatePool from '../components/CandidatePool.vue';
import ExperimentMatrix from '../components/ExperimentMatrix.vue';
import { useBatchRun } from '../composables/useBatchRun';
import { useExperiment } from '../composables/useExperiment';

/**
 * EvalView —— 评测页（P5）。
 *
 * 四个标签页，与 `?tab=` 双向同步：
 *   batch       批量对照测试（F09）
 *   history     历史评测
 *   candidates  候选题池（套餐 §5）
 *   experiment  参数矩阵实验（套餐 E3）
 *
 * 用 query 而不是本地 ref 存当前页签，是为了让「从对话页 👎 → 候选池」这类
 * 跨页跳转可以直接带参数落到目标页签。
 */
type TabKey = 'batch' | 'history' | 'candidates' | 'experiment';

const TABS: Array<{ key: TabKey; label: string }> = [
  { key: 'batch', label: '批量对照' },
  { key: 'history', label: '历史评测' },
  { key: 'candidates', label: '候选题池' },
  { key: 'experiment', label: '参数实验' },
];

const route = useRoute();
const router = useRouter();

const batch = useBatchRun();
const experiment = useExperiment();

/* ---------------------------------------------------------------- 页签 */

const activeTab = computed<TabKey>(() => {
  const raw = route.query.tab;
  const key = typeof raw === 'string' ? raw : '';
  return (TABS.find((t) => t.key === key)?.key ?? 'batch') as TabKey;
});

function setTab(key: TabKey): void {
  void router.replace({ name: 'eval', query: { ...route.query, tab: key } });
}

/* ------------------------------------------------------------ 候选池状态 */

const candidates = ref<EvalCandidate[]>([]);
const candidateSummary = ref<FeedbackSummary | null>(null);
const candidatesLoading = ref(false);
const candidatesError = ref<string | null>(null);
const candidateBusyId = ref<string | null>(null);

/**
 * 历史详情是否展开。
 *
 * 不能只靠 `batch.run` 有没有值来判断：用户先在「批量对照」里跑完一次，
 * `batch.run` 就已经有值了，这时切到「历史评测」会直接顶出一大块详情，
 * 把历史列表挤到看不见。所以详情必须是「点某一行才展开」的显式动作。
 */
const historyDetailOpen = ref(false);

async function loadCandidates(): Promise<void> {
  candidatesLoading.value = true;
  candidatesError.value = null;
  try {
    const [list, summary] = await Promise.all([evalApi.listCandidates(), evalApi.fetchFeedbackSummary()]);
    candidates.value = list;
    candidateSummary.value = summary;
  } catch (e) {
    candidatesError.value = e instanceof ApiError ? e.message : '候选池加载失败';
  } finally {
    candidatesLoading.value = false;
  }
}

async function onDecideCandidate(id: string, status: 'accepted' | 'ignored'): Promise<void> {
  if (candidateBusyId.value) return;
  candidateBusyId.value = id;
  try {
    await evalApi.decideCandidate(id, status);
    const target = candidates.value.find((c) => c.id === id);
    if (target) target.status = status;
    ElMessage.success(status === 'accepted' ? '已纳入实验问题集' : '已忽略该候选');
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.message : '操作失败，请重试');
  } finally {
    candidateBusyId.value = null;
  }
}

/* -------------------------------------------------------------- 事件接线 */

function onMode(value: AnswerMode): void {
  batch.mode.value = value;
}

function onK(value: number): void {
  batch.k.value = value;
}

function onSelectedIds(ids: string[]): void {
  batch.selectedIds.value = ids;
}

async function onStart(): Promise<void> {
  const ok = await batch.start();
  if (ok) ElMessage.success('批量对照测试已完成');
  else if (batch.error.value) ElMessage.error(batch.error.value);
}

async function onOpenRun(id: string): Promise<void> {
  await batch.openRun(id);
  historyDetailOpen.value = true;
}

async function onCreateExperiment(): Promise<void> {
  const ok = await experiment.create();
  if (ok) {
    ElMessage.success('实验已创建，进度会在下方更新');
    setTab('experiment');
  } else if (experiment.conflict.value) {
    ElMessage.warning(experiment.conflict.value);
  }
}

function onToggleAxis(key: Parameters<typeof experiment.toggleAxisValue>[0], value: number | boolean): void {
  experiment.toggleAxisValue(key, value as never);
}

/* ------------------------------------------------------------ 生命周期 */

async function loadTab(tab: TabKey): Promise<void> {
  if (tab === 'batch' && batch.questions.value.length === 0) {
    await batch.loadQuestions();
  }
  if (tab === 'history') {
    await batch.loadHistory();
  }
  if (tab === 'candidates') {
    await loadCandidates();
  }
}

onMounted(async () => {
  await loadTab(activeTab.value);
  // 批量页要能选题目，即使用户直接落在别的页签也先拉一次，
  // 否则切到「批量对照」时会闪一下空列表。
  if (batch.questions.value.length === 0) await batch.loadQuestions();
});

watch(activeTab, (tab) => {
  void loadTab(tab);
});

onBeforeUnmount(() => {
  batch.stopPolling();
  experiment.stopPolling();
});
</script>

<template>
  <section class="eval" data-testid="page-eval">
    <header class="eval__head">
      <div>
        <h1 class="eval__title">评测</h1>
        <p class="eval__desc">
          用固定问题集对照「查资料 / 直接答」，把 badcase 收进候选池，再用参数矩阵找出最优分块配置。
        </p>
      </div>
    </header>

    <nav class="eval__tabs" role="tablist" data-testid="eval-tabs">
      <button
        v-for="tab in TABS"
        :key="tab.key"
        type="button"
        role="tab"
        class="eval__tab"
        :class="{ 'eval__tab--on': activeTab === tab.key }"
        :aria-selected="activeTab === tab.key"
        :data-testid="`tab-${tab.key}`"
        @click="setTab(tab.key)"
      >
        {{ tab.label }}
      </button>
    </nav>

    <div class="eval__body">
      <BatchRunner
        v-if="activeTab === 'batch'"
        :questions="batch.questions.value"
        :selected-ids="batch.selectedIds.value"
        :mode="batch.mode.value"
        :k="batch.k.value"
        :run="batch.run.value"
        :running="batch.running.value"
        :loading="batch.loading.value"
        :error="batch.error.value"
        @update:selected-ids="onSelectedIds"
        @update:mode="onMode"
        @update:k="onK"
        @start="onStart"
        @toggle="batch.toggleQuestion"
        @select-all="batch.selectAll"
        @select-none="batch.selectNone"
      />

      <template v-else-if="activeTab === 'history'">
        <RunHistory
          :runs="batch.history.value"
          :loading="batch.historyLoading.value"
          :error="batch.historyError.value"
          :active-id="batch.run.value?.id ?? null"
          @open="onOpenRun"
          @refresh="batch.loadHistory"
        />

        <div v-if="batch.run.value && historyDetailOpen" class="eval__detail" data-testid="history-detail">
          <BatchRunner
            :questions="batch.questions.value"
            :selected-ids="batch.selectedIds.value"
            :mode="batch.run.value.mode"
            :k="batch.run.value.k"
            :run="batch.run.value"
            :running="batch.running.value"
            :loading="false"
            :error="batch.error.value"
            @update:selected-ids="onSelectedIds"
            @update:mode="onMode"
            @update:k="onK"
            @start="onStart"
            @toggle="batch.toggleQuestion"
            @select-all="batch.selectAll"
            @select-none="batch.selectNone"
          />
        </div>
      </template>

      <CandidatePool
        v-else-if="activeTab === 'candidates'"
        :candidates="candidates"
        :summary="candidateSummary"
        :loading="candidatesLoading"
        :error="candidatesError"
        :busy-id="candidateBusyId"
        @decide="onDecideCandidate"
        @refresh="loadCandidates"
      />

      <ExperimentMatrix
        v-else
        :axes="experiment.axes.value"
        :name="experiment.name.value"
        :group-count="experiment.groupCount.value"
        :experiment="experiment.experiment.value"
        :runs="experiment.runs.value"
        :best="experiment.best.value"
        :creating="experiment.creating.value"
        :polling="experiment.polling.value"
        :progress="experiment.progress.value"
        :error="experiment.error.value"
        :conflict="experiment.conflict.value"
        :is-running="experiment.isRunning.value"
        :is-done="experiment.isDone.value"
        @update:name="(v: string) => (experiment.name.value = v)"
        @toggle="onToggleAxis"
        @create="onCreateExperiment"
        @reset="experiment.reset"
      />
    </div>
  </section>
</template>

<style scoped>
.eval {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px 24px 32px;
  max-width: 1280px;
}

.eval__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.eval__title {
  margin: 0 0 4px;
  font-size: 19px;
  font-weight: 650;
  color: var(--ink);
}

.eval__desc {
  margin: 0;
  font-size: 13px;
  color: var(--muted);
}

.eval__tabs {
  display: flex;
  gap: 2px;
  border-bottom: 1px solid var(--line);
}

.eval__tab {
  padding: 8px 14px;
  font-size: 13px;
  color: var(--muted);
  background: transparent;
  border: 0;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: color 0.15s ease;
}

.eval__tab:hover {
  color: var(--ink);
}

.eval__tab--on {
  color: var(--teal-dark);
  border-bottom-color: var(--teal);
  font-weight: 600;
}

.eval__body {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.eval__detail {
  border-top: 1px dashed var(--line);
  padding-top: 16px;
}
</style>
