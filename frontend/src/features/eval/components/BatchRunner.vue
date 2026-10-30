<script setup lang="ts">
import { computed, ref } from 'vue';
import { ElMessage } from 'element-plus';
import type { AnswerMode, EvalCaseResult, EvalQuestion, EvalRun, EvalStats } from '@/types/api';
import { MODE_OPTIONS, K_MIN, K_MAX } from '@/constants/app';
import { downloadCsv, csvTimestamp, toCsv } from '@/utils/csv';
import { batchCsvRows, excerpt, groupQuestions, passRate, ragAdvantage, summarize, typeLabel, typeTone } from '../composables/batch';

/**
 * BatchRunner —— 批量对照测试面板（F09）。
 *
 * 布局按规格：三个统计卡（总题数 / 不查资料通过 / 查资料通过）→ 问题集选择 →
 * 结果表（每题两种回答并排 + 初判徽章）→ 导出 CSV。
 *
 * 判分徽章是「初判」，表内必须明示仍需人工核对 —— 这是 F09 验收第三条的要求，
 * 也是避免把自动判分当成结论的唯一提示。
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
}>();

const emit = defineEmits<{
  'update:selectedIds': [string[]];
  'update:mode': [AnswerMode];
  'update:k': [number];
  start: [];
  toggle: [string];
  selectAll: [];
  selectNone: [];
}>();

const groups = computed(() => groupQuestions(props.questions));
const cases = computed<EvalCaseResult[]>(() => props.run?.cases ?? []);
const stats = computed<EvalStats>(() => summarize(cases.value));
const advantage = computed(() => ragAdvantage(stats.value));
const hasResult = computed(() => cases.value.length > 0);

/** 展开/收起的回答单元格：表格里只放摘要，点开看全文 */
const expanded = ref<Set<string>>(new Set());
function toggleExpand(questionId: string): void {
  const next = new Set(expanded.value);
  if (next.has(questionId)) next.delete(questionId);
  else next.add(questionId);
  expanded.value = next;
}
function isExpanded(questionId: string): boolean {
  return expanded.value.has(questionId);
}

function isSelected(id: string): boolean {
  return props.selectedIds.includes(id);
}

function onToggle(id: string): void {
  emit('toggle', id);
}

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
    <!-- 统计卡：F09 要求顶部三张 -->
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
        <span class="batch__card-label">查资料通过</span>
        <strong class="batch__card-value">{{ stats.passedRag }}</strong>
        <span class="batch__card-sub">{{ passRate(stats.passedRag, stats.total) }}%</span>
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
        <h3 class="batch__title">问题集（{{ selectedIds.length }} / {{ questions.length }}）</h3>
        <div class="batch__picker-actions">
          <el-button size="small" text data-testid="select-all" @click="emit('selectAll')">全选</el-button>
          <el-button size="small" text data-testid="select-none" @click="emit('selectNone')">全不选</el-button>
        </div>
      </div>

      <div v-if="loading" class="batch__state" data-testid="questions-loading">正在加载题目…</div>
      <div v-else class="batch__groups">
        <div v-for="group in groups" :key="group.type" class="batch__group">
          <span class="batch__group-label">{{ group.label }}</span>
          <el-checkbox
            v-for="q in group.items"
            :key="q.id"
            :model-value="isSelected(q.id)"
            :data-testid="`pick-${q.id}`"
            @update:model-value="onToggle(q.id)"
          >
            {{ q.id }}
          </el-checkbox>
        </div>
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
      <label class="batch__k">
        <span>取回数量 k</span>
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
      <el-button :disabled="!hasResult" data-testid="batch-export" @click="exportCsv">
        导出 CSV
      </el-button>
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

      <table class="batch__table">
        <thead>
          <tr>
            <th class="batch__col-id">题号</th>
            <th class="batch__col-type">题型</th>
            <th class="batch__col-q">问题</th>
            <th class="batch__col-a">不查资料回答</th>
            <th class="batch__col-a">查资料回答</th>
            <th class="batch__col-src">来源</th>
            <th class="batch__col-ms">耗时</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in cases" :key="c.questionId" :data-testid="`case-${c.questionId}`">
            <td class="batch__col-id"><code>{{ c.questionId }}</code></td>
            <td class="batch__col-type">
              <span class="badge" :class="`badge--${typeTone(c.type)}`">{{ typeLabel(c.type) }}</span>
            </td>
            <td class="batch__col-q">{{ c.question }}</td>

            <td class="batch__col-a">
              <span
                class="badge"
                :class="c.directPassed ? 'badge--ok' : 'badge--error'"
                :data-testid="`direct-badge-${c.questionId}`"
              >
                {{ c.directPassed ? '通过' : '未通过' }}
              </span>
              <p class="batch__answer" :class="{ 'batch__answer--open': isExpanded(c.questionId) }">
                {{ isExpanded(c.questionId) ? c.directAnswer : excerpt(c.directAnswer) }}
              </p>
              <button
                type="button"
                class="batch__more"
                :data-testid="`expand-direct-${c.questionId}`"
                @click="toggleExpand(c.questionId)"
              >
                {{ isExpanded(c.questionId) ? '收起' : '展开' }}
              </button>
            </td>

            <td class="batch__col-a">
              <span
                class="badge"
                :class="c.ragPassed ? 'badge--ok' : 'badge--error'"
                :data-testid="`rag-badge-${c.questionId}`"
              >
                {{ c.ragPassed ? '通过' : '未通过' }}
              </span>
              <p class="batch__answer" :class="{ 'batch__answer--open': isExpanded(c.questionId) }">
                {{ isExpanded(c.questionId) ? c.ragAnswer : excerpt(c.ragAnswer) }}
              </p>
              <button
                type="button"
                class="batch__more"
                :data-testid="`expand-rag-${c.questionId}`"
                @click="toggleExpand(c.questionId)"
              >
                {{ isExpanded(c.questionId) ? '收起' : '展开' }}
              </button>
            </td>

            <td class="batch__col-src">
              <span class="batch__sources" :data-testid="`sources-${c.questionId}`">
                {{ c.ragSources.length }}
              </span>
            </td>
            <td class="batch__col-ms">{{ c.elapsedMs }}ms</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-else-if="!running" class="batch__empty" data-testid="batch-empty">
      选择题目后点「开始测试」，跑完会在这里列出每题的两种回答与初判结果。
    </div>
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
  grid-template-columns: repeat(3, minmax(0, 1fr));
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
}

.batch__card--teal {
  border-color: color-mix(in srgb, var(--teal) 40%, var(--line));
  background: color-mix(in srgb, var(--teal) 6%, var(--paper));
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

.batch__card-sub {
  font-size: 12px;
  color: var(--teal-dark);
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
  gap: 4px;
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

.batch__k {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--muted);
}

.batch__error {
  margin: 0;
  font-size: 13px;
  color: var(--red);
}

.batch__state {
  padding: 20px;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
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

.batch__answer {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text);
  white-space: pre-wrap;
  max-height: 4.8em;
  overflow: hidden;
}

.batch__answer--open {
  max-height: none;
}

.batch__more {
  padding: 0;
  font-size: 11px;
  color: var(--teal);
  background: transparent;
  border: 0;
  cursor: pointer;
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

@media (max-width: 900px) {
  .batch__stats {
    grid-template-columns: 1fr;
  }
}
</style>
