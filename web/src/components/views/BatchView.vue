<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { actions, fail, state } from '../../store.js';
import { usePolling } from '../../composables/usePolling.js';
import { toast } from '../../composables/useToast.js';

const running = ref(false);

const bs = computed(() => state.batchState || {});
const rows = computed(() => state.batchRows || []);
const stats = computed(() => bs.value.stats || { total: 0, direct: 0, rag: 0 });

const statsText = computed(() => {
  const s = stats.value;
  return `查资料 ${s.rag}/${s.total} · 不查资料 ${s.direct}/${s.total}`;
});

const barWidth = computed(() => {
  const b = bs.value;
  if (!b.total) return '0%';
  return `${Math.round((b.done / b.total) * 100)}%`;
});

const statusText = computed(() => {
  const b = bs.value;
  if (b.stage === 'running') return `正在运行 ${b.done}/${b.total}${b.current ? ` · ${b.current}` : ''}`;
  if (b.stage === 'error') return b.error;
  if (b.stage === 'done') return b.export_path ? `已导出：${b.export_path}` : '已完成';
  return '';
});

const poller = usePolling(async () => {
  const more = await actions.pollBatch();
  running.value = more;
  return more;
}, 400);

async function run() {
  running.value = true;
  try {
    await actions.runBatch();
    poller.start();
  } catch (err) {
    running.value = false;
    fail(err);
  }
}

async function exportCsv() {
  try {
    const data = await actions.exportBatch();
    toast(`已导出 ${data.name}`);
    await actions.pollBatch();
  } catch (err) {
    fail(err);
  }
}

async function syncOnce() {
  try { await actions.pollBatch(); } catch (err) { fail(err); }
}

onMounted(syncOnce);
watch(() => state.view, (view) => { if (view === 'batch') syncOnce(); });
</script>

<template>
  <section class="view">
    <div class="split">
      <button class="btn primary" :disabled="running" @click="run">
        {{ running ? '正在运行…' : '运行对照测试' }}
      </button>
      <button class="btn" @click="exportCsv">导出 CSV</button>
      <span class="badge">{{ statsText }}</span>
    </div>
    <p class="hint">初判由关键词规则自动给出，仅作参考，报告里仍需人工核对并写明误判情况。</p>
    <div class="progress"><i :style="{ width: barWidth }" /></div>
    <p class="hint">{{ statusText }}</p>

    <div v-if="!rows.length" class="empty">还没有结果</div>
    <div v-else class="table-wrap mt12">
      <table>
        <thead>
          <tr>
            <th style="width:60px">题号</th>
            <th style="width:70px">类型</th>
            <th style="width:200px">问题</th>
            <th>查资料回答</th>
            <th style="width:66px">初判</th>
            <th>不查资料回答</th>
            <th style="width:66px">初判</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td class="mono">{{ row.id }}</td>
            <td>{{ row.type }}</td>
            <td>{{ row.question }}</td>
            <td class="pre-wrap">{{ row.rag_answer }}</td>
            <td :class="row.rag_pass ? 'pass' : 'fail'">{{ row.rag_pass ? '通过' : '未通过' }}</td>
            <td class="pre-wrap">{{ row.direct_answer }}</td>
            <td :class="row.direct_pass ? 'pass' : 'fail'">{{ row.direct_pass ? '通过' : '未通过' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
