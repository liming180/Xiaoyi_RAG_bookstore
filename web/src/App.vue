<script setup>
import { onMounted, ref } from 'vue';
import AppSidebar from './components/AppSidebar.vue';
import TopBar from './components/TopBar.vue';
import NoticeBar from './components/NoticeBar.vue';
import Composer from './components/Composer.vue';
import ToastHost from './components/ToastHost.vue';
import ChatView from './components/views/ChatView.vue';
import TraceView from './components/views/TraceView.vue';
import ChunksView from './components/views/ChunksView.vue';
import BatchView from './components/views/BatchView.vue';
import { actions, state } from './store.js';
import { toast } from './composables/useToast.js';

const booted = ref(false);

onMounted(async () => {
  try {
    await actions.refresh();
    booted.value = true;
  } catch (err) {
    toast(`无法连接后端：${err.message}`);
  }
});
</script>

<template>
  <div class="app">
    <AppSidebar />
    <div class="main">
      <TopBar />
      <NoticeBar />
      <ChatView v-show="state.view === 'chat'" />
      <TraceView v-show="state.view === 'trace'" />
      <ChunksView v-show="state.view === 'chunks'" />
      <BatchView v-show="state.view === 'batch'" />
      <Composer v-show="state.view === 'chat'" />
    </div>
    <ToastHost />
  </div>
</template>
