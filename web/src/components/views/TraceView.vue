<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { actions, fail, state } from '../../store.js';

const loaded = ref(false);

const rows = computed(() => state.lastTrace || []);
const cut = computed(() => rows.value.filter((row) => row.retrieved).length);

async function loadMessages() {
  try { await actions.loadLastMessages(); } catch (err) { fail(err); }
}

async function ensure() {
  if (loaded.value) return;
  await loadMessages();
  loaded.value = true;
}

onMounted(ensure);
watch(() => state.view, (view) => { if (view === 'trace') ensure(); });
</script>

<template>
  <section class="view">
    <h3 class="section-title">检索过程（全部片段按得分降序，前 k 条为本次取回）</h3>
    <div v-if="!rows.length" class="empty">还没有检索记录</div>
    <div v-else class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>排名</th>
            <th>片段编号</th>
            <th>所属资料</th>
            <th>相似度</th>
            <th>摘录</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, index) in rows"
            :key="row.chunk_id"
            :class="{ retrieved: row.retrieved, cut: index === cut - 1 }"
          >
            <td class="num">{{ row.rank }}</td>
            <td class="mono">{{ row.chunk_id }}</td>
            <td>
              {{ row.source }}
              <span v-if="!row.verified" class="badge warn">未核实</span>
            </td>
            <td class="num">{{ Number(row.score).toFixed(4) }}</td>
            <td class="truncate" :title="row.excerpt">{{ row.excerpt }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h3 class="section-title">最近一次发送的消息</h3>
    <div v-if="!state.lastMessages.length" class="empty">还没有请求</div>
    <div v-else class="table-wrap">
      <table>
        <thead>
          <tr>
            <th style="width:110px">角色</th>
            <th>内容</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(msg, index) in state.lastMessages" :key="index">
            <td class="mono">{{ msg.role }}</td>
            <td class="pre-wrap">{{ msg.content }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
