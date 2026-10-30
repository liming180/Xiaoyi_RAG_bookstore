<script setup lang="ts">
import { computed, ref } from 'vue';
import type { RetrievalTrace, TraceRow } from '@/types/api';
import { positionText, scoreWidth, truncate } from '@/utils/text';

/**
 * RetrievalTrace —— 检索过程面板（F08）。
 *
 * 展示全量候选（多于 k），retrieved=true 的是真正进入回答的片段，
 * 其余是「召回了但被重排淘汰」—— 这正是教学演示要看的东西。
 */
const props = defineProps<{
  trace: RetrievalTrace;
}>();

const open = ref(false);

const rows = computed<TraceRow[]>(() => props.trace.rows ?? []);
const kept = computed(() => rows.value.filter((r) => r.retrieved).length);

const summary = computed(
  () =>
    `${props.trace.question} · k=${props.trace.k} · 片段 ${props.trace.chunkSize} 字 / 重叠 ${props.trace.overlap} 字`,
);

function toggle(): void {
  open.value = !open.value;
}
</script>

<template>
  <section class="trace" data-testid="retrieval-trace">
    <button type="button" class="trace__toggle" :aria-expanded="open" @click="toggle">
      <span class="trace__title">检索过程</span>
      <span class="trace__meta">候选 {{ rows.length }} 段 · 采用 {{ kept }} 段</span>
      <span class="trace__chevron" :class="{ 'trace__chevron--open': open }">▾</span>
    </button>

    <div v-if="open" class="trace__body">
      <p class="trace__question">{{ summary }}</p>

      <table class="trace__table">
        <thead>
          <tr>
            <th class="trace__col-rank">#</th>
            <th class="trace__col-chunk">片段</th>
            <th>文件 / 位置</th>
            <th class="trace__col-score">得分</th>
            <th class="trace__col-flag">结果</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.chunkId + row.rank"
            :class="{ 'trace__row--kept': row.retrieved }"
            :data-testid="row.retrieved ? 'trace-row-kept' : 'trace-row-dropped'"
          >
            <td class="trace__col-rank">{{ row.rank }}</td>
            <td class="trace__col-chunk">
              <code>{{ row.chunkId }}</code>
            </td>
            <td>
              <div class="trace__doc">{{ row.docTitle }}</div>
              <div class="trace__pos">{{ positionText(row.start, row.end) }}</div>
              <div class="trace__text">{{ truncate(row.text, 90) }}</div>
            </td>
            <td class="trace__col-score">
              <div class="trace__bar">
                <div class="trace__fill" :style="{ width: scoreWidth(row.score) }" />
              </div>
              <span class="trace__num">{{ row.score.toFixed(2) }}</span>
            </td>
            <td class="trace__col-flag">
              <span v-if="row.retrieved" class="trace__badge trace__badge--kept">采用</span>
              <span v-else class="trace__badge trace__badge--drop">淘汰</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.trace {
  margin: 0 20px 8px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--paper);
  overflow: hidden;
}

.trace__toggle {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 12px;
  background: transparent;
  border: 0;
  cursor: pointer;
  text-align: left;
}

.trace__title {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
}

.trace__meta {
  font-size: 11px;
  color: var(--muted);
}

.trace__chevron {
  margin-left: auto;
  font-size: 11px;
  color: var(--muted);
  transition: transform 0.15s;
}

.trace__chevron--open {
  transform: rotate(180deg);
}

.trace__body {
  padding: 0 12px 12px;
}

.trace__question {
  margin: 0 0 8px;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--muted);
}

.trace__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.trace__table th {
  padding: 4px 6px;
  text-align: left;
  font-weight: 600;
  color: var(--muted);
  border-bottom: 1px solid var(--line);
}

.trace__table td {
  padding: 6px;
  vertical-align: top;
  border-bottom: 1px solid var(--line);
}

.trace__row--kept {
  background: color-mix(in srgb, var(--teal) 6%, transparent);
}

.trace__col-rank {
  width: 28px;
  color: var(--muted);
  font-family: var(--font-mono);
}

.trace__col-chunk {
  width: 84px;
}

.trace__col-chunk code {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--teal);
}

.trace__col-score {
  width: 96px;
}

.trace__col-flag {
  width: 52px;
}

.trace__doc {
  font-weight: 600;
  color: var(--ink);
}

.trace__pos {
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--muted);
}

.trace__text {
  margin-top: 2px;
  color: var(--muted);
  line-height: 1.5;
}

.trace__bar {
  height: 4px;
  background: var(--line);
  border-radius: 999px;
  overflow: hidden;
}

.trace__fill {
  height: 100%;
  background: var(--teal);
}

.trace__num {
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--muted);
}

.trace__badge {
  display: inline-block;
  padding: 1px 6px;
  font-size: 10px;
  border-radius: 999px;
}

.trace__badge--kept {
  color: var(--teal-dark);
  background: var(--soft);
}

.trace__badge--drop {
  color: var(--muted);
  background: var(--line);
}
</style>
