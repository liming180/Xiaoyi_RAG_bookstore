<script setup lang="ts">
import { computed } from 'vue';
import type { EvalRunSummary } from '@/types/api';
import { formatTime, passRate, runStatusLabel, runStatusTone } from '../composables/batch';

/**
 * RunHistory —— 历史评测列表（F09 第二项）。
 *
 * 列表只显示摘要（时间/模式/k/通过数），点开才拉详情 —— 与后端「列表不带 cases」
 * 的契约一致，避免列表接口把 10 段长回答一起吐出来。
 */
const props = defineProps<{
  runs: EvalRunSummary[];
  loading?: boolean;
  activeId?: string | null;
}>();

const emit = defineEmits<{
  open: [string];
  refresh: [];
}>();

const rows = computed(() => [...props.runs].sort((a, b) => b.createdAt - a.createdAt));

function onOpen(id: string): void {
  emit('open', id);
}
</script>

<template>
  <section class="history" data-testid="run-history">
    <header class="history__head">
      <h2 class="history__title">历史评测</h2>
      <el-button size="small" data-testid="history-refresh" @click="emit('refresh')">刷新</el-button>
    </header>

    <div v-if="loading" class="history__state" data-testid="history-loading">正在加载历史…</div>
    <div v-else-if="rows.length === 0" class="history__state" data-testid="history-empty">
      还没有评测记录。到「批量对照」标签页跑一次测试。
    </div>

    <table v-else class="history__table">
      <thead>
        <tr>
          <th>时间</th>
          <th>模式</th>
          <th>k</th>
          <th>题数</th>
          <th>不查资料</th>
          <th>查资料</th>
          <th>状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="run in rows"
          :key="run.id"
          :data-testid="`history-row-${run.id}`"
          :class="{ 'history__row--active': activeId === run.id }"
        >
          <td class="history__time">{{ formatTime(run.createdAt) }}</td>
          <td>{{ run.mode }}</td>
          <td class="history__num">{{ run.k }}</td>
          <td class="history__num">{{ run.stats?.total ?? 0 }}</td>
          <td class="history__num">{{ run.stats?.passedDirect ?? 0 }}</td>
          <td class="history__num history__num--teal">{{ run.stats?.passedRag ?? 0 }}</td>
          <td>
            <span class="badge" :class="`badge--${runStatusTone(run.status)}`">
              {{ runStatusLabel(run.status) }}
            </span>
          </td>
          <td>
            <el-button
              size="small"
              text
              :data-testid="`history-open-${run.id}`"
              @click="onOpen(run.id)"
            >
              查看详情
            </el-button>
          </td>
        </tr>
      </tbody>
    </table>

    <p v-if="rows.length > 0" class="history__foot">
      最近一次查资料通过率 {{ passRate(rows[0]?.stats?.passedRag ?? 0, rows[0]?.stats?.total ?? 0) }}%
    </p>
  </section>
</template>

<style scoped>
.history {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.history__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.history__title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.history__state {
  padding: 32px;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
  background: var(--paper);
  border: 1px dashed var(--line);
  border-radius: var(--radius);
}

.history__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
}

.history__table th {
  padding: 8px 12px;
  text-align: left;
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
  background: var(--bg);
  border-bottom: 1px solid var(--line);
}

.history__table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
}

.history__table tbody tr:last-child td {
  border-bottom: 0;
}

.history__row--active {
  background: color-mix(in srgb, var(--teal) 7%, transparent);
}

.history__time {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--muted);
}

.history__num {
  width: 76px;
  text-align: right;
  font-family: var(--font-mono);
  font-size: 12px;
}

.history__num--teal {
  color: var(--teal-dark);
  font-weight: 600;
}

.history__foot {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
}
</style>
