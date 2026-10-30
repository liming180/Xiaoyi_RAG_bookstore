<script setup>
import { nextTick, ref, watch } from 'vue';
import ChatTurn from '../ChatTurn.vue';
import { state } from '../../store.js';

const log = ref(null);

watch(
  () => state.turns.length,
  async () => {
    await nextTick();
    if (log.value) log.value.scrollTop = log.value.scrollHeight;
  },
);
</script>

<template>
  <section class="view">
    <div ref="log" class="chat-log">
      <div v-if="!state.turns.length" class="empty">先在左侧建库，再提一个问题试试。</div>
      <ChatTurn v-for="turn in state.turns" :key="turn.id" :turn="turn" />
    </div>
  </section>
</template>
