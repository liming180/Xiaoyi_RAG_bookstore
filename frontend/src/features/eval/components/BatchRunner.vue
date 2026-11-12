<script setup lang="ts">
import { computed, ref } from 'vue';
import { ElMessage } from 'element-plus';
import type { AnswerMode, EvalCaseResult, EvalQuestion, EvalRun, EvalStats } from '@/types/api';
import { MODE_OPTIONS, K_MIN, K_MAX } from '@/constants/app';
import { downloadCsv, csvTimestamp, toCsv } from '@/utils/csv';
import ListSkeleton from '@/components/ListSkeleton.vue';
import {
  avgElapsed,
  batchCsvRows,
  excerpt,
  filterCases,
  groupQuestions,
  passRate,
  ragAdvantage,
  summarize,
  typeHint,
  typeLabel,
  typeTone,
  type FilterKey,
} from '../composables/batch';

/**
 * BatchRunner —— 批量对照测试面板（F09 + P5-01…P5-05 交互闭环）。
 *
 * 布局：四张统计卡（总题数 / 不查资料 / 查资料+通过率环 / 平均耗时）→
 * 问题集选择 → 参数与启动 → 执行进度条 → 结果筛选条 → 结果表 → 单题详情浮层。
 *
 * 判分徽章是「初判」，表内必须明示仍需人工核对 —— F09 验收第三条的要求。
 */
const props = defineProps<{
  questions: EvalQuestion[];
  selectedIds: string[];
  mode: AnswerMode;
  k: number;
  run: EvalRun | null;
  running: boolean;
  loading?: boolean;
  error?: string | null;
  /** 题型开关（P5-08）：空 = 不限题型 */
  selectedTypes: string[];
  /** 数量模式：all = 全部筛选结果，limit = 随机抽 N 道 */
  countMode: 'all' | 'limit';
  limitCount: number;
}>();

const emit = defineEmits<{
  'update:selectedIds': [string[]];
  'update:mode': [AnswerMode];
  'update:k': [number];
  'update:countMode': ['all' | 'limit'];
  'update:limitCount': [number];
  /** 切换题型开关 */
  toggleType: [string];
  start: [];
  toggle: [string];
  selectAll: [];
  selectNone: [];
  /** 随机抽 n 道 */
  pickRandom: [number];
  /** 重跑未通过题：参数是 rag 侧未通过的题号列表（P5-04 闭环） */
  rerun: [string[]];
}>();

const groups = computed(() => groupQuestions(props.questions));

/* ------------------------------------------------------ 题型开关与数量 */

/** 三种题型的启用题数与当前是否打开 */
const typeOptions = computed(() =>
  (['single', 'cross', 'out'] as const).map((type) => ({
    type,
    label: typeLabel(type),
    hint: typeHint(type),
    count: props.questions.filter((q) => q.type === type && q.enabled !== false).length,
    on: props.selectedTypes.includes(type),
  })),
);

/**
 * 按当前条件能测多少道。
 *
 * 精确点选时就是勾选数；条件筛选时是「打开题型里启用题的总数」，
 * 数量模式为 limit 时取 limit 与实际可用的较小值 —— 与后端 selectQuestions 的口径一致。
 */
const plannedCount = computed(() => {
  if (props.selectedIds.length > 0) return props.selectedIds.length;
  const types = props.selectedTypes;
  const available = props.questions.filter(
    (q) => q.enabled !== false && (types.length === 0 || types.includes(q.type)),
  ).length;
  if (props.countMode === 'limit') return Math.min(props.limitCount, available);
  return available;
});
const cases = computed<EvalCaseResult[]>(() => props.run?.cases ?? []);
const stats = computed<EvalStats>(() => summarize(cases.value));
const advantage = computed(() => ragAdvantage(stats.value));
const hasResult = computed(() => cases.value.length > 0);

/* -------------------------------------------------------------- 结果筛选 */

const filter = ref<FilterKey>('all');
const visibleCases = computed(() => filterCases(cases.value, filter.value));

const failedCases = computed(() => cases.value.filter((c) => !c.ragPassed));
const failedCount = computed(() => failedCases.value.length);

/**
 * 筛选条：全部 / 未通过 / 三种题型，各自带行数。
 *
 * chip 里用短标签（新题型全称太长会撑爆筛选条），完整含义放 title。
 */
const FILTER_SHORT_LABELS: Record<string, string> = {
  single: '单份资料',
  cross: '综合多篇',
  out: '库外题',
};
const filters = computed(() => {
  const count = (key: FilterKey): number => filterCases(cases.value, key).length;
  return [
    { key: 'all' as FilterKey, label: '全部', count: count('all') },
    { key: 'failed' as FilterKey, label: '查资料未通过', count: count('failed') },
    { key: 'single' as FilterKey, label: FILTER_SHORT_LABELS.single, count: count('single') },
    { key: 'cross' as FilterKey, label: FILTER_SHORT_LABELS.cross, count: count('cross') },
    { key: 'out' as FilterKey, label: FILTER_SHORT_LABELS.out, count: count('out') },
  ];
});

/* -------------------------------------------------------------- 统计衍生 */

const avgMs = computed(() => avgElapsed(cases.value));
const ragRate = computed(() => passRate(stats.value.passedRag, stats.value.total));

/** 通过率环：SVG stroke-dashoffset 实现，不引图表库 */
const RING_R = 26;
const RING_C = 2 * Math.PI * RING_R;
const ringOffset = computed(() => RING_C * (1 - Math.min(ragRate.value, 100) / 100));

/* -------------------------------------------------------------- 执行进度 */

const progressPct = computed(() => Math.min(Math.max(props.run?.progress ?? 0, 0), 100));

/* ------------------------------------------------------------ 单题详情浮层 */

const dialogCase = ref<EvalCaseResult | null>(null);
function openDetail(c: EvalCaseResult): void {
  dialogCase.value = c;
}
function closeDetail(): void {
  dialogCase.value = null;
}

/* ---------------------------------------------------------------- 选择集 */

function isSelected(id: string): boolean {
  return props.selectedIds.includes(id);
}
function onToggle(id: string): void {
  emit('toggle', id);
}

/* ---------------------------------------------------------- 随机抽题 */

/** 想测的题数；空输入框时按钮置灰 */
const pickCount = ref<number | null>(null);
function onPickRandom(): void {
  const n = Number(pickCount.value ?? 0);
  if (n > 0) emit('pickRandom', n);
}

/* ------------------------------------------------------- 重跑未通过闭环 */

function rerunFailed(): void {
  if (failedCount.value === 0 || props.running) return;
  emit('rerun', failedCases.value.map((c) => c.questionId));
}

/* ---------------------------------------------------------------- 导出 */

function exportCsv(): void {
  if (cases.value.length === 0) {
    ElMessage.warning('还没有结果可导出');
    return;
  }
  downloadCsv(`批量对照-${csvTimestamp()}.csv`, toCsv(batchCsvRows(cases.value)));
  ElMessage.success('已导出 CSV');
}
</script>

<template>
  <section class="batch" data-testid="batch-runner">
    <!-- 统计卡：总题数 / 不查资料 / 查资料（带通过率环）/ 平均耗时 -->
    <div class="batch__stats">
      <div class="batch__card" data-testid="stat-total">
        <span class="batch__card-label">总题数</span>
        <strong class="batch__card-value">{{ stats.total }}</strong>
      </div>
      <div class="batch__card" data-testid="stat-direct">
        <span class="batch__card-label">不查资料通过</span>
        <strong class="batch__card-value">{{ stats.passedDirect }}</strong>
        <span class="batch__card-sub">{{ passRate(stats.passedDirect, stats.total) }}%</span>
      </div>
      <div class="batch__card batch__card--teal" data-testid="stat-rag">
        <div class="batch__card-main">
          <span class="batch__card-label">查资料通过</span>
          <strong class="batch__card-value">{{ stats.passedRag }}</strong>
          <span class="batch__card-sub">{{ passRate(stats.passedRag, stats.total) }}%</span>
        </div>
        <svg
          v-if="hasResult"
          class="batch__ring"
          viewBox="0 0 64 64"
          data-testid="stat-rag-ring"
          role="img"
          :aria-label="`查资料通过率 ${ragRate}%`"
        >
          <circle class="batch__ring-track" cx="32" cy="32" :r="RING_R" />
          <circle
            class="batch__ring-bar"
            cx="32"
            cy="32"
            :r="RING_R"
            :stroke-dasharray="RING_C"
            :stroke-dashoffset="ringOffset"
          />
          <text class="batch__ring-text" x="32" y="36">{{ ragRate }}%</text>
        </svg>
      </div>
      <div class="batch__card" data-testid="stat-avg">
        <span class="batch__card-label">平均耗时</span>
        <strong class="batch__card-value batch__card-value--small">{{ avgMs }}<small>ms</small></strong>
        <span class="batch__card-sub">每题两路回答合计</span>
      </div>
    </div>

    <p v-if="hasResult" class="batch__verdict" data-testid="batch-verdict">
      <template v-if="advantage.better">
        查资料比不查资料多通过 {{ advantage.diff }} 题，检索链路有效。
      </template>
      <template v-else-if="advantage.diff > 0">
        查资料多通过 {{ advantage.diff }} 题，优势不明显，建议检查召回质量。
      </template>
      <template v-else> 查资料未取得优势，请检查知识库是否已建库、检索参数是否合理。 </template>
    </p>

    <!-- 问题集选择 -->
    <div class="batch__picker" data-testid="question-picker">
      <div class="batch__picker-head">
        <h3 class="batch__title">
          问题集（{{ selectedIds.length }} / {{ questions.length }}）
          <span class="batch__picker-tip">勾选要测的题；跑的题越多越慢</span>
        </h3>
        <div class="batch__picker-actions">
          <el-input-number
            v-model="pickCount"
            size="small"
            :min="1"
            :max="questions.length || 13"
            placeholder="N"
            style="width: 92px"
            data-testid="random-count"
            aria-label="随机抽题数量"
          />
          <el-button
            size="small"
            text
            type="primary"
            :disabled="!pickCount || pickCount < 1"
            data-testid="random-pick"
            title="从 13 道题里随机抽 N 道，适合小批快速试跑"
            @click="onPickRandom"
          >
            随机抽
          </el-button>
          <el-button size="small" text data-testid="select-all" @click="emit('selectAll')">全选</el-button>
          <el-button size="small" text data-testid="select-none" @click="emit('selectNone')">全不选</el-button>
        </div>
      </div>

      <ListSkeleton v-if="loading" data-testid="questions-loading" :rows="3" label="正在加载题目…" />
      <div v-else class="batch__groups">
        <div v-for="group in groups" :key="group.type" class="batch__group">
          <span
            class="batch__group-label"
            :title="typeHint(group.type)"
          >{{ group.label }} ⓘ</span>
          <el-checkbox
            v-for="q in group.items"
            :key="q.id"
            :model-value="isSelected(q.id)"
            :data-testid="`pick-${q.id}`"
            :title="`${q.id}：${q.question}`"
            @update:model-value="onToggle(q.id)"
          >
            {{ q.id }}
          </el-checkbox>
        </div>
      </div>
    </div>

    <!-- 题型开关 + 数量：不想逐题勾选时，按题型和题数选（P5-08） -->
    <div class="batch__scope" data-testid="batch-scope">
      <div class="batch__scope-row">
        <span class="batch__scope-label">题型</span>
        <el-check-tag
          v-for="opt in typeOptions"
          :key="opt.type"
          :checked="opt.on"
          :data-testid="`type-toggle-${opt.type}`"
          :title="opt.hint"
          @change="emit('toggleType', opt.type)"
        >
          {{ opt.label }} <b>{{ opt.count }}</b>
        </el-check-tag>
        <span class="batch__scope-hint">勾了上面的具体题号时，以题号为准</span>
      </div>

      <div class="batch__scope-row">
        <span class="batch__scope-label">测几道</span>
        <el-radio-group
          :model-value="countMode"
          size="small"
          data-testid="count-mode"
          @update:model-value="(v: string | number | boolean | undefined) => emit('update:countMode', v === 'limit' ? 'limit' : 'all')"
        >
          <el-radio-button value="all">全部（{{ plannedCount }} 道）</el-radio-button>
          <el-radio-button value="limit">随机抽</el-radio-button>
        </el-radio-group>
        <el-input-number
          :model-value="limitCount"
          :min="1"
          :max="Math.max(props.questions.length, 1)"
          size="small"
          :disabled="countMode !== 'limit'"
          style="width: 100px"
          data-testid="limit-count"
          @update:model-value="(v: number | undefined) => emit('update:limitCount', Number(v ?? 1))"
        />
        <span class="batch__scope-hint">
          本次将测 <b class="batch__scope-num">{{ plannedCount }}</b> 道
        </span>
      </div>
    </div>

    <!-- 参数与启动 -->
    <div class="batch__controls">
      <el-segmented
        :model-value="mode"
        :options="MODE_OPTIONS.map((m) => ({ label: m.label, value: m.value }))"
        data-testid="batch-mode"
        @update:model-value="(v: AnswerMode) => emit('update:mode', v)"
      />
      <label
        class="batch__k"
        title="每次检索从知识库取回的资料片段数（不是题数），k 越大上下文越多但更慢"
      >
        <span>检索片段数 k ⓘ</span>
        <el-input-number
          :model-value="k"
          :min="K_MIN"
          :max="K_MAX"
          size="small"
          data-testid="batch-k"
          @update:model-value="(v: number | undefined) => emit('update:k', Number(v ?? K_MIN))"
        />
      </label>
      <el-button
        type="primary"
        :loading="running"
        :disabled="running || selectedIds.length === 0"
        data-testid="batch-start"
        @click="emit('start')"
      >
        {{ running ? '测试中…' : '开始测试' }}
      </el-button>
      <el-button
        v-if="failedCount > 0 && !running"
        type="warning"
        plain
        data-testid="rerun-failed"
        @click="rerunFailed"
      >
        重跑未通过（{{ failedCount }}）
      </el-button>
      <el-button :disabled="!hasResult" data-testid="batch-export" @click="exportCsv">
        导出 CSV
      </el-button>
    </div>

    <!-- 执行进度：轮询期间给一条细进度条，替代干等的「测试中…」 -->
    <div v-if="running" class="batch__progress" data-testid="batch-progress">
      <i class="batch__progress-bar" :style="{ width: `${progressPct}%` }" />
      <span class="batch__progress-text">{{ progressPct }}%</span>
    </div>

    <p v-if="error" class="batch__error" data-testid="batch-error">{{ error }}</p>

    <!-- 结果表 -->
    <div v-if="hasResult" class="batch__result" data-testid="batch-result">
      <div class="batch__result-head">
        <span class="batch__hint" data-testid="batch-hint">
          初判结果由关键词命中自动判定，仍需人工核对。
        </span>
        <span v-if="run" class="batch__meta">
          {{ run.mode }} · k={{ run.k }} · {{ cases.length }} 题
        </span>
      </div>

      <!-- 筛选条：全部 / 未通过 / 题型，行数实时跟随 -->
      <div class="batch__filters" data-testid="batch-filters">
        <button
          v-for="f in filters"
          :key="f.key"
          type="button"
          class="batch__chip"
          :class="{ 'batch__chip--on': filter === f.key }"
          :data-testid="`batch-filter-${f.key}`"
          :title="f.key === 'all' ? '显示本次全部结果' : f.key === 'failed' ? '查资料侧未通过的题，即 badcase' : typeHint(f.key)"
          @click="filter = f.key"
        >
          {{ f.label }}
          <b>{{ f.count }}</b>
        </button>
      </div>

      <table v-if="visibleCases.length > 0" class="batch__table">
        <thead>
          <tr>
            <th class="batch__col-id">题号</th>
            <th class="batch__col-type">题型</th>
            <th class="batch__col-q">问题</th>
            <th v-if="mode !== 'rag'" class="batch__col-a">不查资料回答</th>
            <th v-if="mode !== 'direct'" class="batch__col-a">查资料回答</th>
            <th class="batch__col-src">来源</th>
            <th class="batch__col-ms">耗时</th>
            <th class="batch__col-op">详情</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="c in visibleCases"
            :key="c.questionId"
            :data-testid="`case-${c.questionId}`"
            :class="{ 'batch__row--fail': !c.ragPassed }"
          >
            <td class="batch__col-id"><code>{{ c.questionId }}</code></td>
            <td class="batch__col-type">
              <span class="badge" :class="`badge--${typeTone(c.type)}`">{{ typeLabel(c.type) }}</span>
            </td>
            <td class="batch__col-q">{{ c.question }}</td>

            <td v-if="mode !== 'rag'" class="batch__col-a">
              <span
                class="badge"
                :class="c.directPassed ? 'badge--ok' : 'badge--error'"
                :data-testid="`direct-badge-${c.questionId}`"
              >
                {{ c.directPassed ? '通过' : '未通过' }}
              </span>
              <p class="batch__answer">{{ excerpt(c.directAnswer) }}</p>
            </td>

            <td v-if="mode !== 'direct'" class="batch__col-a">
              <span
                class="badge"
                :class="c.ragPassed ? 'badge--ok' : 'badge--error'"
                :data-testid="`rag-badge-${c.questionId}`"
              >
                {{ c.ragPassed ? '通过' : '未通过' }}
              </span>
              <p class="batch__answer">{{ excerpt(c.ragAnswer) }}</p>
            </td>

            <td class="batch__col-src">
              <span class="batch__sources" :data-testid="`sources-${c.questionId}`">
                {{ c.ragSources.length }}
              </span>
            </td>
            <td class="batch__col-ms">{{ c.elapsedMs }}ms</td>
            <td class="batch__col-op">
              <el-button
                size="small"
                text
                type="primary"
                :data-testid="`detail-${c.questionId}`"
                @click="openDetail(c)"
              >
                查看
              </el-button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="batch__filter-empty" data-testid="batch-filter-empty">
        当前筛选下没有结果，换个条件试试。
      </div>
    </div>

    <div v-else-if="!running" class="batch__empty" data-testid="batch-empty">
      选择题目后点「开始测试」，跑完会在这里列出每题的两种回答与初判结果。
    </div>

    <!-- 单题详情浮层：两种回答全文并排 + 来源清单 -->
    <Teleport to="body">
      <div v-if="dialogCase" class="bdialog" data-testid="case-dialog" @click.self="closeDetail">
        <div class="bdialog__card" role="dialog" aria-modal="true">
          <header class="bdialog__head">
            <div>
              <span class="badge" :class="`badge--${typeTone(dialogCase.type)}`">
                {{ typeLabel(dialogCase.type) }}
              </span>
              <code class="bdialog__id">{{ dialogCase.questionId }}</code>
              <strong class="bdialog__q">{{ dialogCase.question }}</strong>
            </div>
            <el-button
              size="small"
              circle
              data-testid="case-dialog-close"
              aria-label="关闭详情"
              @click="closeDetail"
            >
              ✕
            </el-button>
          </header>

          <div class="bdialog__panes">
            <div class="bdialog__pane">
              <div class="bdialog__pane-head">
                <span class="badge" :class="dialogCase.directPassed ? 'badge--ok' : 'badge--error'">
                  {{ dialogCase.directPassed ? '通过' : '未通过' }}
                </span>
                <span class="bdialog__pane-title">不查资料回答</span>
              </div>
              <p class="bdialog__text">{{ dialogCase.directAnswer || '（空回答）' }}</p>
            </div>

            <div class="bdialog__pane bdialog__pane--rag">
              <div class="bdialog__pane-head">
                <span class="badge" :class="dialogCase.ragPassed ? 'badge--ok' : 'badge--error'">
                  {{ dialogCase.ragPassed ? '通过' : '未通过' }}
                </span>
                <span class="bdialog__pane-title">查资料回答</span>
              </div>
              <p class="bdialog__text">{{ dialogCase.ragAnswer || '（空回答）' }}</p>
              <div v-if="dialogCase.ragSources.length > 0" class="bdialog__srcs">
                <span class="bdialog__srcs-label">引用来源（{{ dialogCase.ragSources.length }}）：</span>
                <code v-for="s in dialogCase.ragSources" :key="s" class="bdialog__src">{{ s }}</code>
              </div>
            </div>
          </div>

          <footer class="bdialog__foot">
            耗时 {{ dialogCase.elapsedMs }}ms · 初判由关键词命中自动判定，仍需人工核对。
          </footer>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.batch {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.batch__stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.batch__card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 14px 16px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  transition: box-shadow 0.15s ease;
}

.batch__card:hover {
  box-shadow: var(--shadow);
}

.batch__card--teal {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  border-color: color-mix(in srgb, var(--teal) 40%, var(--line));
  background: color-mix(in srgb, var(--teal) 6%, var(--paper));
}

.batch__card-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.batch__card-label {
  font-size: 12px;
  color: var(--muted);
}

.batch__card-value {
  font-size: 26px;
  font-weight: 650;
  color: var(--ink);
  line-height: 1.2;
}

.batch__card-value--small {
  font-size: 20px;
}

.batch__card-value small {
  margin-left: 2px;
  font-size: 12px;
  font-weight: 500;
  color: var(--muted);
}

.batch__card-sub {
  font-size: 12px;
  color: var(--teal-dark);
}

.batch__ring {
  width: 64px;
  height: 64px;
  flex: none;
}

.batch__ring-track {
  fill: none;
  stroke: var(--line);
  stroke-width: 7;
}

.batch__ring-bar {
  fill: none;
  stroke: var(--teal);
  stroke-width: 7;
  stroke-linecap: round;
  transform: rotate(-90deg);
  transform-origin: 32px 32px;
  transition: stroke-dashoffset 0.4s ease;
}

.batch__ring-text {
  font-size: 13px;
  font-weight: 600;
  fill: var(--ink);
  text-anchor: middle;
}

.batch__verdict {
  margin: 0;
  padding: 10px 14px;
  font-size: 13px;
  color: var(--ink);
  background: var(--soft);
  border-left: 3px solid var(--teal);
  border-radius: var(--radius-sm);
}

.batch__picker {
  padding: 14px 16px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.batch__picker-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.batch__title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.batch__picker-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.batch__picker-tip {
  margin-left: 8px;
  font-size: 12px;
  font-weight: 400;
  color: var(--muted);
}

.batch__groups {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 20px;
}

.batch__group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.batch__group-label {
  font-size: 12px;
  color: var(--muted);
}

.batch__controls {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.batch__scope {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 16px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.batch__scope-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.batch__scope-label {
  flex: none;
  min-width: 44px;
  font-size: 12px;
  color: var(--muted);
}

.batch__scope-hint {
  font-size: 12px;
  color: var(--muted);
}

.batch__scope-num {
  color: var(--teal-dark);
  font-weight: 650;
}

.batch__k {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--muted);
}

.batch__progress {
  display: flex;
  align-items: center;
  gap: 10px;
}

.batch__progress-bar {
  position: relative;
  display: block;
  flex: 1;
  height: 6px;
  background: var(--teal);
  border-radius: 999px;
  overflow: hidden;
  transition: width 0.4s ease;
}

.batch__progress-bar::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    transparent,
    color-mix(in srgb, var(--paper) 55%, transparent),
    transparent
  );
  animation: batch-sheen 1.2s linear infinite;
}

@keyframes batch-sheen {
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(100%);
  }
}

.batch__progress-text {
  flex: none;
  min-width: 40px;
  text-align: right;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--muted);
}

.batch__error {
  margin: 0;
  font-size: 13px;
  color: var(--red);
}

.batch__result {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
}

.batch__result-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: var(--bg);
  border-bottom: 1px solid var(--line);
}

.batch__hint {
  font-size: 12px;
  color: var(--amber);
}

.batch__meta {
  font-size: 12px;
  color: var(--muted);
  font-family: var(--font-mono);
}

.batch__filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
}

.batch__chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  font-size: 12px;
  color: var(--muted);
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.batch__chip b {
  font-weight: 600;
  color: var(--ink);
}

.batch__chip:hover {
  color: var(--ink);
  border-color: var(--teal);
}

.batch__chip--on {
  color: var(--paper);
  background: var(--teal);
  border-color: var(--teal);
}

.batch__chip--on b {
  color: var(--paper);
}

.batch__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.batch__table th {
  padding: 8px 10px;
  text-align: left;
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
  background: var(--bg);
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}

.batch__table td {
  padding: 10px;
  vertical-align: top;
  border-bottom: 1px solid var(--line);
}

.batch__table tbody tr:last-child td {
  border-bottom: 0;
}

.batch__row--fail {
  background: color-mix(in srgb, var(--red) 5%, transparent);
}

.batch__row--fail td:first-child {
  box-shadow: inset 3px 0 0 var(--red);
}

.batch__col-id {
  width: 56px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--muted);
}

.batch__col-type {
  width: 74px;
}

.batch__col-q {
  width: 200px;
  font-weight: 500;
}

.batch__col-a {
  min-width: 220px;
}

.batch__col-src,
.batch__col-ms {
  width: 62px;
  text-align: right;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--muted);
}

.batch__col-op {
  width: 64px;
}

.batch__answer {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text);
}

.batch__filter-empty {
  padding: 24px;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
}

.batch__empty {
  padding: 32px;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
  background: var(--paper);
  border: 1px dashed var(--line);
  border-radius: var(--radius);
}

/* ------------------------------------------------------- 单题详情浮层 */

.bdialog {
  position: fixed;
  inset: 0;
  z-index: 2100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 26, 22, 0.45);
  backdrop-filter: blur(2px);
}

.bdialog__card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: min(880px, 100%);
  max-height: min(76vh, 720px);
  overflow: auto;
  padding: 18px 20px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}

.bdialog__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.bdialog__id {
  margin: 0 8px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--muted);
}

.bdialog__q {
  font-size: 15px;
  color: var(--ink);
}

.bdialog__panes {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.bdialog__pane {
  padding: 12px;
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}

.bdialog__pane--rag {
  border-color: color-mix(in srgb, var(--teal) 35%, var(--line));
}

.bdialog__pane-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.bdialog__pane-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
}

.bdialog__text {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
}

.bdialog__srcs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
}

.bdialog__srcs-label {
  font-size: 12px;
  color: var(--muted);
}

.bdialog__src {
  padding: 1px 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--teal-dark);
  background: var(--soft);
  border-radius: 4px;
}

.bdialog__foot {
  padding-top: 8px;
  font-size: 12px;
  color: var(--muted);
  border-top: 1px dashed var(--line);
}

@media (max-width: 1100px) {
  .batch__stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .bdialog__panes {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .batch__stats {
    grid-template-columns: 1fr;
  }
}
</style>
