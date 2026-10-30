<script setup>
import { computed } from 'vue';
import { actions, kbBadge, state } from '../store.js';

const views = [
  { key: 'chat', label: '对话' },
  { key: 'trace', label: '检索过程' },
  { key: 'chunks', label: '片段浏览' },
  { key: 'batch', label: '批量对照' },
];

const badge = computed(() => kbBadge(state.status));
const statusText = computed(() => {
  if (!state.status) return '资料 0 份 · 分块 —';
  return `资料 ${state.status.doc_count} 份 · 分块 ${state.status.chunk_size}/${state.status.chunk_overlap}`;
});

function go(key) {
  state.view = key;
  actions.setView(key);
}
</script>

<template>
  <header class="topbar">
    <div class="tabs">
      <button
        v-for="item in views"
        :key="item.key"
        class="tab"
        :class="{ active: state.view === item.key }"
        :data-view="item.key"
        @click="go(item.key)"
      >{{ item.label }}</button>
    </div>
    <div class="status-line">
      <span :class="badge.cls">{{ badge.text }}</span>
      <span>{{ statusText }}</span>
    </div>
  </header>
</template>
