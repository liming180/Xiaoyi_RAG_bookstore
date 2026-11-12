<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import type { AnswerMode, EvalCandidate, FeedbackSummary } from '@/types/api';
import { evalApi } from '@/api';
import { ApiError } from '@/api';
import { downloadBlob } from '@/utils/csv';
import BatchRunner from '../components/BatchRunner.vue';
import RunHistory from '../components/RunHistory.vue';
import CandidatePool from '../components/CandidatePool.vue';
import QuestionBank from '../components/QuestionBank.vue';
import ExperimentMatrix from '../components/ExperimentMatrix.vue';
import { useBatchRun } from '../composables/useBatchRun';
import { useExperiment } from '../composables/useExperiment';
import { useQuestionBank } from '../composables/useQuestionBank';

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
type TabKey = 'batch' | 'history' | 'candidates' | 'questionbank' | 'experiment';

const TABS: Array<{ key: TabKey; label: string }> = [
  { key: 'batch', label: '批量对照' },
  { key: 'history', label: '历史评测' },
  { key: 'candidates', label: '候选题池' },
  { key: 'questionbank', label: '题库管理' },
  { key: 'experiment', label: '参数实验' },
];

const route = useRoute();
const router = useRouter();

const batch = useBatchRun();
const experiment = useExperiment();
const bank = useQuestionBank();

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

/*
 * 历史详情现在由 RunHistory 自己管展开态（内联在卡片下方），
 * 这里只负责把拉到的 run 传进去 —— 原来那个「列表下方一大块详情」的
 * historyDetailOpen 开关已随 BatchRunner 复用一起删掉。
 */

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

async function onDecideCandidate(
  id: string,
  status: 'accepted' | 'ignored',
  keywords?: string,
): Promise<void> {
  if (candidateBusyId.value) return;
  candidateBusyId.value = id;
  try {
    await evalApi.decideCandidate(id, status, keywords);
    const target = candidates.value.find((c) => c.id === id);
    if (target) target.status = status;
    if (status === 'accepted') {
      // 补了关键词才算「能计分」；没补的要当场说清楚，别等报告出来才发现少算一题。
      ElMessage.success(
        keywords && keywords.trim() !== ''
          ? '已纳入实验问题集（可计分）'
          : '已纳入实验问题集（未填关键词，进实验后不计分）',
      );
    } else {
      ElMessage.success('已忽略该候选');
    }
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.message : '操作失败，请重试');
  } finally {
    candidateBusyId.value = null;
  }
}

/**
 * 导出已采纳候选为题库 CSV。
 *
 * 走 `evalApi.exportCandidates()` 拿 Blob 再在前端触发下载：这条端点回 `text/csv`，
 * 直接 `window.open` 会把 Bearer token 丢掉（token 在 axios 拦截器里加），必然 401。
 */
const exporting = ref(false);

async function onExportCandidates(): Promise<void> {
  if (exporting.value) return;
  exporting.value = true;
  try {
    const blob = await evalApi.exportCandidates();
    downloadBlob('eval-candidates.csv', blob);
    ElMessage.success('已导出候选题库，补完 keywords 后可贴回 assets/eval/questions.csv');
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.message : '导出失败，请重试');
  } finally {
    exporting.value = false;
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
  if (ok) {
    ElMessage.success('批量对照测试已完成');
    // 跑完立即刷新历史列表，不然要等用户手动点「刷新」才能看到这次记录。
    void batch.loadHistory();
  } else if (batch.error.value) {
    ElMessage.error(batch.error.value);
  }
}

/**
 * 重跑未通过题（P5-04）：把选题切成 failed 集合后走同一条 start 链路。
 *
 * 直接改 selectedIds 再调 start，而不是另开接口 —— 后端 /eval/batch 本来就
 * 支持任选题目，闭环在前端完成，契约零改动。
 */
async function onRerunFailed(ids: string[]): Promise<void> {
  if (ids.length === 0 || batch.running.value) return;
  batch.selectedIds.value = ids;
  const ok = await batch.start();
  if (ok) {
    ElMessage.success(`已重跑 ${ids.length} 道未通过题`);
    void batch.loadHistory();
  } else if (batch.error.value) {
    ElMessage.error(batch.error.value);
  }
}

/**
 * 展开某次历史评测的详情。
 *
 * 详情是异步拉的（列表接口不带 cases），所以要自己管「加载中 / 失败」两态 ——
 * 否则点「查看详情」后那一瞬间是空白，用户会以为按钮没反应。
 */
const historyDetailLoading = ref(false);
const historyDetailError = ref<string | null>(null);

async function onOpenRun(id: string): Promise<void> {
  // 已经展开过同一条就不重复拉
  if (batch.run.value?.id === id && !historyDetailError.value) return;
  historyDetailLoading.value = true;
  historyDetailError.value = null;
  try {
    await batch.openRun(id);
    if (!batch.run.value) historyDetailError.value = '没能加载这次评测的详情';
  } catch (e) {
    historyDetailError.value = e instanceof ApiError ? e.message : '详情加载失败，请重试';
  } finally {
    historyDetailLoading.value = false;
  }
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
  if (tab === 'questionbank') {
    await bank.load();
  }
}

/* ---------------------------------------------------------- 题库管理 */

/**
 * 保存题目草稿。
 *
 * 题库改动会影响「批量对照」的选题范围，所以成功后同时刷新评测侧的题目列表，
 * 否则用户改完题切回批量页签，看到的还是旧的 13 道。
 */
async function onSaveQuestion(draft: Parameters<typeof bank.save>[0]): Promise<void> {
  const ok = await bank.save(draft);
  if (ok) {
    ElMessage.success('已保存');
    await batch.loadQuestions();
  } else if (bank.error.value) {
    ElMessage.error(bank.error.value);
  }
}

async function onRemoveQuestion(q: { id: string; source: string }): Promise<void> {
  const ok = await bank.remove(q as never);
  if (ok) {
    ElMessage.success(`已删除 ${q.id}`);
    await batch.loadQuestions();
  } else if (bank.error.value) {
    ElMessage.error(bank.error.value);
  }
}

async function onToggleQuestion(q: never): Promise<void> {
  await bank.toggleEnabled(q);
  if (bank.error.value) ElMessage.error(bank.error.value);
  else await batch.loadQuestions();
}

async function onImportQuestions(csv: string): Promise<void> {
  const result = await bank.importCsv(csv);
  if (result) {
    ElMessage.success(`导入完成：新增 ${result.created} 条，跳过 ${result.skipped} 条`);
    if (result.errors.length > 0) {
      // 逐行错误用 warning 列出：跳过是预期行为，但用户得知道哪几行没进去。
      ElMessage.warning(result.errors.slice(0, 3).join('；'));
    }
    await batch.loadQuestions();
  } else if (bank.error.value) {
    ElMessage.error(bank.error.value);
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
        :selected-types="batch.selectedTypes.value"
        :count-mode="batch.countMode.value"
        :limit-count="batch.limitCount.value"
        @update:selected-ids="onSelectedIds"
        @update:mode="onMode"
        @update:k="onK"
        @update:count-mode="(v: 'all' | 'limit') => (batch.countMode.value = v)"
        @update:limit-count="(v: number) => (batch.limitCount.value = v)"
        @toggle-type="batch.toggleType"
        @start="onStart"
        @rerun="onRerunFailed"
        @toggle="batch.toggleQuestion"
        @select-all="batch.selectAll"
        @select-none="batch.selectNone"
        @pick-random="batch.pickRandom"
      />

      <template v-else-if="activeTab === 'history'">
        <RunHistory
          :runs="batch.history.value"
          :loading="batch.historyLoading.value"
          :error="batch.historyError.value"
          :active-id="batch.run.value?.id ?? null"
          :detail="batch.run.value"
          :detail-loading="historyDetailLoading"
          :detail-error="historyDetailError"
          @open="onOpenRun"
          @refresh="batch.loadHistory"
        />

      </template>

      <QuestionBank
        v-else-if="activeTab === 'questionbank'"
        :questions="bank.questions.value"
        :loading="bank.loading.value"
        :error="bank.error.value"
        :busy-code="bank.busyCode.value"
        :saving="bank.saving.value"
        :importing="bank.importing.value"
        :exporting="bank.exporting.value"
        :editing="bank.editing.value"
        @close-editor="bank.closeEdit"
        @refresh="bank.load"
        @create="bank.openCreate"
        @edit="bank.openEdit"
        @save="onSaveQuestion"
        @remove="onRemoveQuestion"
        @toggle-enabled="onToggleQuestion"
        @import="onImportQuestions"
        @export="bank.exportCsv"
      />

      <CandidatePool
        v-else-if="activeTab === 'candidates'"
        :candidates="candidates"
        :summary="candidateSummary"
        :loading="candidatesLoading"
        :error="candidatesError"
        :busy-id="candidateBusyId"
        :exporting="exporting"
        @decide="onDecideCandidate"
        @refresh="loadCandidates"
        @export="onExportCandidates"
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
