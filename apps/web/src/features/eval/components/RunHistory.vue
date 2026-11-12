<script setup lang="ts">
import { computed, ref } from 'vue';
import type { EvalCaseResult, EvalRun, EvalRunSummary } from '@/types/api';
import ListSkeleton from '@/components/ListSkeleton.vue';
import RunResultTable from './RunResultTable.vue';
import { passRate, runStatusLabel, runStatusTone, trendPoints } from '../composables/batch';
import { formatAgo, formatDateTime, formatDuration } from '@/utils/time';

/**
 * RunHistory —— 历史评测列表（F09 第二项）。
 *
 * 列表只显示摘要（时间/模式/k/通过数），点开才拉详情 —— 与后端「列表不带 cases」
 * 的契约一致，避免列表接口把 10 段长回答一起吐出来。
 *
 * 换肤改动（2026-11-09）：表格 → 卡片。
 *
 * 原因（实测截图）：8 列挤一张表，「时间/模式/k/题数/不查资料/查资料/状态/操作」
 * 每列都窄到只能放 3-4 个字；加上 A-1 的秒/毫秒缺陷，时间全显示成 1970，
 * 整个列表读不出「哪次实验更好」这个核心信息。
 *
 * 卡片的信息层级：左侧通过率环（一眼可比）→ 中间规模与两路对比条 → 右侧耗时与入口。
 * 新增「耗时」列（finishedAt - createdAt），后端本来就有这个字段，之前没展示。
 */
const props = defineProps<{
  runs: EvalRunSummary[];
  loading?: boolean;
  activeId?: string | null;
  /** 加载失败时的文案；列表页三态（加载中 / 空 / 出错）必须齐，缺一个用户就只能盯着空白猜。 */
  error?: string | null;
  /**
   * 当前展开的那次评测详情（含 cases）。
   *
   * 详情由父层拉取后传回来 —— 列表接口按契约不带 cases，不能指望列表里有。
   * 传 null 表示还在加载 / 没展开。
   */
  detail?: EvalRun | null;
  /** 详情加载中 */
  detailLoading?: boolean;
  /** 详情加载失败文案 */
  detailError?: string | null;
}>();

const emit = defineEmits<{
  open: [string];
  refresh: [];
}>();

const rows = computed(() => [...props.runs].sort((a, b) => b.createdAt - a.createdAt));

/**
 * 最近若干次「查资料通过率」sparkline（P5-06）。
 *
 * 点序列为旧→新；只有 2 个点以上才值得画线，单次运行画不出趋势。
 * 用纯 SVG polyline，不引图表库 —— 一条折线的复杂度配不上一个依赖。
 */
const points = computed(() => trendPoints(props.runs));
const hasTrend = computed(() => points.value.length >= 2);

/** 100×36 视窗下的 polyline 坐标：纵向留 4px 上下边距，横向均分 */
const trendLine = computed(() => {
  const w = 100;
  const h = 28;
  const n = points.value.length;
  return points.value
    .map((p, i) => {
      const x = n === 1 ? w / 2 : (i / (n - 1)) * w;
      const y = 4 + (1 - p.rate / 100) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
});

/* ---- 通过率环几何 ---- */
const RING_R = 28;
const RING_C = 2 * Math.PI * RING_R;

function ringOffset(passed: number, total: number): number {
  return RING_C * (1 - passRate(passed, total) / 100);
}

function ragRate(run: EvalRunSummary): number {
  return passRate(run.stats?.passedRag ?? 0, run.stats?.total ?? 0);
}

/** 两路对比条的宽度百分比 */
function barWidth(passed: number, total: number): string {
  if (!total) return '0%';
  return `${Math.min(100, Math.round((passed / total) * 100))}%`;
}

/**
 * 内联展开：点「查看详情」在这张卡片下方就地展开结果表。
 *
 * 为什么不用「滚到底部再渲染」：原实现在列表之后塞一整块 BatchRunner，
 * 卡片和详情被列表里其余 7 条记录隔开，展开后用户得往下滚很久才看到结果，
 * 而且那整块带着选题面板和「开始测试 / 重跑未通过」工具栏 —— 历史记录是
 * 只读的，这些控件既不该出现，也容易被误当成能改这次的结果。
 *
 * 现在详情跟着卡片走：展开 → 卡片高亮 + 结果表紧跟其后 + 按钮变「收起详情」。
 * 一次只展开一条，再点别的会切换过去，避免多块大表同时撑长页面。
 */
const openId = ref<string | null>(null);

function toggle(run: EvalRunSummary): void {
  if (openId.value === run.id) {
    openId.value = null;
    return;
  }
  openId.value = run.id;
  emit('open', run.id);
}

/** 单题详情浮层：历史详情里点「查看」用 */
const dialogCase = ref<EvalCaseResult | null>(null);
function onDetail(c: EvalCaseResult): void {
  dialogCase.value = c;
}
function closeDetail(): void {
  dialogCase.value = null;
}
</script>

<template>
  <section class="history" data-testid="run-history">
    <header class="history__head">
      <h2 class="history__title">历史评测</h2>
      <el-button size="small" data-testid="history-refresh" @click="emit('refresh')">刷新</el-button>
    </header>

    <ListSkeleton v-if="loading" data-testid="history-loading" :rows="3" label="正在加载历史…" />
    <div v-else-if="error" class="history__state history__state--error" data-testid="history-error">
      {{ error }}
    </div>
    <div v-else-if="rows.length === 0" class="history__state" data-testid="history-empty">
      还没有评测记录。到「批量对照」标签页跑一次测试。
    </div>

    <div v-else class="history__cards">
      <div
        v-for="run in rows"
        :key="run.id"
        class="history__item"
        :class="{ 'history__item--open': openId === run.id }"
      >
      <article
        class="run"
        :class="{ 'run--active': activeId === run.id }"
        :data-testid="`history-row-${run.id}`"
      >
        <div class="run__ring">
          <svg viewBox="0 0 68 68" role="img" :aria-label="`查资料通过率 ${ragRate(run)}%`">
            <circle class="run__ring-track" cx="34" cy="34" :r="RING_R" />
            <circle
              class="run__ring-bar"
              cx="34"
              cy="34"
              :r="RING_R"
              :stroke-dasharray="RING_C.toFixed(1)"
              :stroke-dashoffset="ringOffset(run.stats?.passedRag ?? 0, run.stats?.total ?? 0).toFixed(1)"
            />
          </svg>
          <div class="run__ring-text">
            <span class="run__ring-num">{{ ragRate(run) }}%</span>
            <span class="run__ring-cap">查资料</span>
          </div>
        </div>

        <div class="run__mid">
          <div class="run__top">
            <span class="run__time" :data-testid="`history-time-${run.id}`">
              {{ formatDateTime(run.createdAt) }}
            </span>
            <span class="run__ago">{{ formatAgo(run.createdAt) }}</span>
            <span class="badge" :class="`badge--${runStatusTone(run.status)}`">
              {{ runStatusLabel(run.status) }}
            </span>
          </div>

          <div class="run__meta">
            <span>题数 <b>{{ run.stats?.total ?? 0 }}</b></span>
            <span>查资料 <b class="run__num--rag">{{ run.stats?.passedRag ?? 0 }}</b></span>
            <span v-if="run.mode === 'both'">
              直接答 <b class="run__num--direct">{{ run.stats?.passedDirect ?? 0 }}</b>
            </span>
            <span v-else class="run__only">仅查资料</span>
            <span class="run__k">k={{ run.k }}</span>
            <span class="run__bar" aria-hidden="true">
              <i
                class="run__bar-rag"
                :style="{ width: barWidth(run.stats?.passedRag ?? 0, run.stats?.total ?? 0) }"
              />
              <i
                v-if="run.mode === 'both'"
                class="run__bar-direct"
                :style="{ width: barWidth(run.stats?.passedDirect ?? 0, run.stats?.total ?? 0) }"
              />
            </span>
          </div>
        </div>

        <div class="run__right">
          <span class="run__dur" :data-testid="`history-dur-${run.id}`">
            {{ formatDuration(run.createdAt, run.finishedAt) }}
          </span>
          <el-button
            size="small"
            text
            :data-testid="`history-open-${run.id}`"
            @click="toggle(run)"
          >
            {{ openId === run.id ? '收起详情 ↑' : '查看详情 ↓' }}
          </el-button>
        </div>
      </article>

      <!-- 内联展开：结果表紧跟在被点开的卡片下面 -->
      <div
        v-if="openId === run.id"
        class="history__detail"
        :data-testid="`history-detail-${run.id}`"
      >
        <ListSkeleton v-if="detailLoading" :rows="3" label="正在加载本次结果…" />
        <div v-else-if="detailError" class="history__state history__state--error">
          {{ detailError }}
        </div>
        <RunResultTable
          v-else-if="detail && detail.id === run.id"
          :run="detail"
          @detail="onDetail"
        />
      </div>
      </div>
    </div>

    <!-- 单题详情浮层：与批量对照页同一套信息，但只读 -->
    <div
      v-if="dialogCase"
      class="hdialog"
      data-testid="history-case-dialog"
      @click.self="closeDetail"
    >
      <div class="hdialog__card">
        <header class="hdialog__head">
          <span class="hdialog__id">{{ dialogCase.questionId }}</span>
          <span class="badge" :class="dialogCase.ragPassed ? 'badge--ok' : 'badge--error'">
            查资料{{ dialogCase.ragPassed ? '通过' : '未通过' }}
          </span>
          <button type="button" class="hdialog__x" aria-label="关闭" @click="closeDetail">
            ✕
          </button>
        </header>
        <p class="hdialog__q">{{ dialogCase.question }}</p>
        <div class="hdialog__panes">
          <section class="hdialog__pane">
            <span class="hdialog__pane-title">不查资料回答</span>
            <p class="hdialog__text">{{ dialogCase.directAnswer || '（无）' }}</p>
          </section>
          <section class="hdialog__pane">
            <span class="hdialog__pane-title">查资料回答</span>
            <p class="hdialog__text">{{ dialogCase.ragAnswer || '（无）' }}</p>
          </section>
        </div>
      </div>
    </div>

    <div v-if="hasTrend" class="history__trend" data-testid="history-trend">
      <span class="history__trend-label">最近 {{ points.length }} 次查资料通过率</span>
      <svg class="history__spark" viewBox="0 0 100 36" preserveAspectRatio="none" role="img" aria-label="通过率趋势">
        <polyline class="history__spark-line" :points="trendLine" />
      </svg>
      <span class="history__trend-now">{{ points[points.length - 1]?.rate }}%</span>
    </div>

    <p v-if="rows.length > 0" class="history__foot">
      最近一次查资料通过率 {{ passRate(rows[0]?.stats?.passedRag ?? 0, rows[0]?.stats?.total ?? 0) }}%
    </p>
  </section>
</template>

<style scoped>
.history {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.history__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.history__title {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
  color: var(--ink);
}

.history__state {
  padding: var(--s8);
  text-align: center;
  font-size: 13px;
  color: var(--muted);
  background: var(--paper);
  border: 1px dashed var(--line);
  border-radius: var(--radius);
}

.history__state--error {
  color: var(--red);
  border-color: var(--red);
  background: var(--red-soft);
}

/* ---- 卡片列表 ---- */
.history__cards {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

/* 一条历史 = 卡片 + 可能展开的详情，两者共享一个外框感 */
.history__item {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.history__item--open .run {
  border-color: var(--teal);
  box-shadow: var(--shadow-sm);
}

.history__detail {
  padding: 0 0 var(--s2);
}

/* ---- 单题详情浮层 ---- */
.hdialog {
  position: fixed;
  inset: 0;
  z-index: 2100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--s6);
  background: rgba(15, 26, 22, 0.45);
  backdrop-filter: blur(2px);
}

.hdialog__card {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  width: min(860px, 100%);
  max-height: 82vh;
  padding: var(--s4);
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow-lg);
  overflow-y: auto;
}

.hdialog__head {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.hdialog__id {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 650;
  color: var(--teal-dark);
}

.hdialog__x {
  margin-left: auto;
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  padding: 0;
  font-size: 13px;
  color: var(--faint);
  background: transparent;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
}

.hdialog__x:hover {
  color: var(--ink);
  background: var(--hover);
}

.hdialog__q {
  margin: 0;
  font-size: 14px;
  font-weight: 550;
  color: var(--ink);
}

.hdialog__panes {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s3);
}

@media (max-width: 760px) {
  .hdialog__panes {
    grid-template-columns: 1fr;
  }
}

.hdialog__pane {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  padding: var(--s3);
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}

.hdialog__pane-title {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--faint);
}

.hdialog__text {
  margin: 0;
  font-size: 13px;
  line-height: 1.72;
  color: var(--text);
  white-space: pre-wrap;
}

.run {
  display: grid;
  grid-template-columns: 68px 1fr auto;
  gap: var(--s4);
  align-items: center;
  padding: var(--s3) var(--s4);
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  transition:
    border-color 0.15s var(--ease),
    box-shadow 0.15s var(--ease);
}

.run:hover {
  border-color: var(--teal-line);
  box-shadow: var(--shadow-sm);
}

.run--active {
  border-color: var(--teal);
  box-shadow: var(--shadow-sm);
}

.run__ring {
  position: relative;
  width: 68px;
  height: 68px;
  flex: none;
}

.run__ring svg {
  width: 68px;
  height: 68px;
  transform: rotate(-90deg);
}

.run__ring-track {
  fill: none;
  stroke: var(--line);
  stroke-width: 6;
}

.run__ring-bar {
  fill: none;
  stroke: var(--teal);
  stroke-width: 6;
  stroke-linecap: round;
  transition: stroke-dashoffset 0.5s var(--ease);
}

.run__ring-text {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.run__ring-num {
  font-family: var(--font-mono);
  font-size: 15px;
  font-weight: 700;
  color: var(--teal-dark);
  line-height: 1.1;
}

.run__ring-cap {
  font-size: 9.5px;
  color: var(--faint);
}

.run__mid {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}

.run__top {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}

.run__time {
  font-family: var(--font-mono);
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink);
}

.run__ago {
  font-size: 11px;
  color: var(--faint);
}

.run__meta {
  display: flex;
  align-items: center;
  gap: var(--s3);
  flex-wrap: wrap;
  font-size: 11.5px;
  color: var(--muted);
}

.run__meta b {
  font-family: var(--font-mono);
  font-weight: 650;
  color: var(--text);
}

.run__meta .run__num--rag {
  color: var(--teal-dark);
}

.run__meta .run__num--direct {
  color: var(--amber);
}

.run__only {
  opacity: 0.6;
}

.run__k {
  font-family: var(--font-mono);
}

.run__bar {
  flex: 1;
  min-width: 70px;
  height: 5px;
  display: flex;
  background: var(--line);
  border-radius: 999px;
  overflow: hidden;
}

.run__bar i {
  display: block;
  height: 100%;
}

.run__bar-rag {
  background: var(--teal);
}

.run__bar-direct {
  background: var(--amber);
}

.run__right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 3px;
}

.run__dur {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--faint);
}

/* ---- 趋势条（保留原实现） ---- */
.history__trend {
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: 10px 14px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.history__trend-label {
  flex: none;
  font-size: 12px;
  color: var(--muted);
}

.history__spark {
  flex: 1;
  height: 36px;
}

.history__spark-line {
  fill: none;
  stroke: var(--teal);
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
  vector-effect: non-scaling-stroke;
}

.history__trend-now {
  flex: none;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  color: var(--teal-dark);
}

.history__foot {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
}
</style>
