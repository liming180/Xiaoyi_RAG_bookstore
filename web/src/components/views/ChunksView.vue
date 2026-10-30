<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { actions, fail, state } from '../../store.js';
import { highlightSegments } from '../../utils/text.js';

const source = ref('');
const keyword = ref('');
const loaded = ref(false);

const rows = computed(() => state.chunks.rows || []);
const summary = computed(() => {
  const c = state.chunks;
  if (!c.rows.length && !loaded.value) return '';
  return `${c.total} 条 · ${c.size}/${c.overlap}`;
});

async function load() {
  try {
    await actions.loadChunks(source.value, keyword.value.trim());
    loaded.value = true;
  } catch (err) {
    fail(err);
  }
}

function onSearch() {
  load();
}

onMounted(load);
watch(() => state.view, (view) => { if (view === 'chunks') load(); });
</script>

<template>
  <section class="view">
    <h3 class="section-title">片段浏览（按资料查看原文位置，或按关键词搜索片段）</h3>

    <div class="split">
      <select v-model="source" style="padding:5px 8px;border:1px solid var(--line);border-radius:9px;background:#fff" @change="onSearch">
        <option value="">全部资料</option>
        <option v-for="doc in state.docs" :key="doc.name" :value="doc.name">{{ doc.name }}</option>
      </select>
      <input
        v-model="keyword"
        placeholder="关键词，如：续借"
        style="flex:1;min-width:160px;padding:5px 10px;border:1px solid var(--line);border-radius:9px;background:#fff"
        @keydown.enter.prevent="onSearch"
      >
      <button class="btn" @click="onSearch">搜索</button>
      <span class="hint">{{ summary }}</span>
    </div>

    <div v-if="!rows.length" class="empty">{{ loaded ? '没有匹配的片段' : '选择资料或输入关键词' }}</div>
    <div v-else class="table-wrap mt12">
      <table>
        <thead>
          <tr>
            <th style="width:110px">片段编号</th>
            <th style="width:180px">所属资料</th>
            <th style="width:150px">原文位置</th>
            <th>片段内容</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.chunk_id">
            <td class="mono">{{ row.chunk_id }}</td>
            <td>
              {{ row.source }}
              <span v-if="!row.verified" class="badge warn">未核实</span>
            </td>
            <td class="mono">{{ row.position }}</td>
            <td class="pre-wrap">
              <template v-for="(seg, i) in highlightSegments(row.text, keyword)" :key="i">
                <mark v-if="seg.hit" style="background:#fdf0c8">{{ seg.text }}</mark>
                <template v-else>{{ seg.text }}</template>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
