<script setup>
import DocList from './DocList.vue';
import ChunkSettings from './ChunkSettings.vue';
import RetrievalSettings from './RetrievalSettings.vue';
import ModelStatus from './ModelStatus.vue';
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <span class="brand-mark">星</span>
      <h1>星河读书会</h1>
    </div>
    <p class="brand-sub">个人资料助手 · 本地知识库</p>
    <DocList />
    <ChunkSettings />
    <RetrievalSettings />
    <ModelStatus />
  </aside>
</template>
