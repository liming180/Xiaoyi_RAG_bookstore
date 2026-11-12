<script setup lang="ts">
import { computed, ref } from 'vue';
import type { EvalCaseResult, EvalRun } from '@/types/api';
import { excerpt, filterCases, typeHint, typeLabel, typeTone, type FilterKey } from '../composables/batch';

/**
 * RunResultTable —— 单次评测的结果表（历史评测「查看详情」专用）。
 *
 * 为什么不直接复用 BatchRunner：
 * BatchRunner 是「跑测试」的完整工作台 —— 选题面板（题库勾选）+ 题型/题数筛选 +
 * 模式与 k + 开始/重跑/导出工具栏 + 结果表。历史评测点「查看详情」要看的只是
 * **已经跑完的那次结果**，把工作台整块塞进详情里，会在结果表上方多出两屏
 * 与「这次跑完了什么」无关的配置控件（选题、开始测试、重跑未通过…），
 * 用户要滚很久才看到结果，且容易误以为还能改这些参数。
 *
 * 所以这里只保留「只读结果」这一层：
 *   头（判定说明 + 本次参数）→ 筛选条 → 结果表。
 * 单题详情浮层由父层（RunHistory）负责，这个组件只抛出 detail 事件。
 */
const props = defineProps<{
  run: EvalRun;
}>();

const emit = defineEmits<{
  /** 点「查看」：把单题详情交给父层渲染浮层 */
  detail: [EvalCaseResult];
}>();

const cases = computed<EvalCaseResult[]>(() => props.run.cases ?? []);
const mode = computed(() => props.run.mode);

const filter = ref<FilterKey>('all');

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

const visibleCases = computed(() => filterCases(cases.value, filter.value));
</script>

<template>
  <div class="result" data-testid="history-result">
    <div class="result__head">
      <span class="result__hint" data-testid="history-result-hint">
        初判结果由关键词命中自动判定，仍需人工核对。
      </span>
      <span class="result__meta">
        {{ mode }} · k={{ run.k }} · {{ cases.length }} 题
      </span>
    </div>

    <div class="result__filters" data-testid="history-result-filters">
      <button
        v-for="f in filters"
        :key="f.key"
        type="button"
        class="result__chip"
        :class="{ 'result__chip--on': filter === f.key }"
        :data-testid="`history-filter-${f.key}`"
        :title="
          f.key === 'all'
            ? '显示本次全部结果'
            : f.key === 'failed'
              ? '查资料侧未通过的题，即 badcase'
              : typeHint(f.key)
        "
        @click="filter = f.key"
      >
        {{ f.label }}
        <b>{{ f.count }}</b>
      </button>
    </div>

    <div class="result__scroll">
      <table v-if="visibleCases.length > 0" class="result__table">
        <thead>
          <tr>
            <th class="result__col-id">题号</th>
            <th class="result__col-type">题型</th>
            <th class="result__col-q">问题</th>
            <th v-if="mode !== 'rag'" class="result__col-a">不查资料回答</th>
            <th v-if="mode !== 'direct'" class="result__col-a">查资料回答</th>
            <th class="result__col-src">来源</th>
            <th class="result__col-ms">耗时</th>
            <th class="result__col-op">详情</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="c in visibleCases"
            :key="c.questionId"
            :data-testid="`case-${c.questionId}`"
            :class="{ 'result__row--fail': !c.ragPassed }"
          >
            <td class="result__col-id"><code>{{ c.questionId }}</code></td>
            <td class="result__col-type">
              <span class="badge" :class="`badge--${typeTone(c.type)}`">{{ typeLabel(c.type) }}</span>
            </td>
            <td class="result__col-q">{{ c.question }}</td>

            <td v-if="mode !== 'rag'" class="result__col-a">
              <span
                class="badge"
                :class="c.directPassed ? 'badge--ok' : 'badge--error'"
                :data-testid="`direct-badge-${c.questionId}`"
              >
                {{ c.directPassed ? '通过' : '未通过' }}
              </span>
              <p class="result__answer">{{ excerpt(c.directAnswer) }}</p>
            </td>

            <td v-if="mode !== 'direct'" class="result__col-a">
              <span
                class="badge"
                :class="c.ragPassed ? 'badge--ok' : 'badge--error'"
                :data-testid="`rag-badge-${c.questionId}`"
              >
                {{ c.ragPassed ? '通过' : '未通过' }}
              </span>
              <p class="result__answer">{{ excerpt(c.ragAnswer) }}</p>
            </td>

            <td class="result__col-src">
              <span class="result__sources" :data-testid="`sources-${c.questionId}`">
                {{ c.ragSources.length }}
              </span>
            </td>
            <td class="result__col-ms">{{ c.elapsedMs }}ms</td>
            <td class="result__col-op">
              <el-button
                size="small"
                text
                type="primary"
                :data-testid="`detail-${c.questionId}`"
                @click="emit('detail', c)"
              >
                查看
              </el-button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="result__empty" data-testid="history-filter-empty">
        当前筛选下没有结果，换个条件试试。
      </div>
    </div>
  </div>
</template>

<style scoped>
.result {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
}

.result__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  padding: 10px 14px;
  background: var(--bg);
  border-bottom: 1px solid var(--line);
}

.result__hint {
  font-size: 12px;
  color: var(--amber);
}

.result__meta {
  font-size: 12px;
  font-family: var(--font-mono);
  color: var(--muted);
  white-space: nowrap;
}

.result__filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
}

.result__chip {
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
  transition: all 0.15s var(--ease);
}

.result__chip b {
  font-weight: 600;
  color: var(--ink);
}

.result__chip:hover {
  color: var(--ink);
  border-color: var(--teal);
}

.result__chip--on {
  color: var(--paper);
  background: var(--teal);
  border-color: var(--teal);
}

.result__chip--on b {
  color: var(--paper);
}

/* 表格横向可滚：详情里列多，窄屏不能把整页撑宽 */
.result__scroll {
  overflow-x: auto;
}

.result__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.result__table th {
  padding: 8px 10px;
  text-align: left;
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
  background: var(--bg);
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}

.result__table td {
  padding: 10px;
  vertical-align: top;
  border-bottom: 1px solid var(--line);
}

.result__table tbody tr:last-child td {
  border-bottom: 0;
}

.result__row--fail {
  background: color-mix(in srgb, var(--red) 5%, transparent);
}

.result__row--fail td:first-child {
  box-shadow: inset 3px 0 0 var(--red);
}

.result__col-id {
  width: 56px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--muted);
}

.result__col-type {
  width: 74px;
}

.result__col-q {
  width: 200px;
  font-weight: 500;
}

.result__col-a {
  min-width: 220px;
}

.result__col-src,
.result__col-ms {
  width: 62px;
  text-align: right;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--muted);
}

.result__col-op {
  width: 64px;
}

.result__answer {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text);
}

.result__empty {
  padding: 24px;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
}
</style>
