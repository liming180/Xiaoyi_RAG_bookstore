<script setup>
import { computed } from 'vue';
import { state } from '../store.js';

/* 通知条：stale 且后端给出 message 时提示「资料或分块设置已改变」，
 * 否则在有 message（例如尚未建库）时显示原文；都没有则隐藏。
 * 与旧版 web/legacy/app.js:114-125 的判定顺序一致。
 */
const payload = computed(() => {
  const status = state.status;
  if (!status) return null;
  if (status.stale && status.message) return { lead: '资料或分块设置已改变。', text: status.message };
  if (status.ready) return null;
  if (status.message) return { lead: '', text: status.message };
  return null;
});
</script>

<template>
  <div class="notice" :class="{ hidden: !payload }">
    <span v-if="payload"><b v-if="payload.lead">{{ payload.lead }}</b>{{ payload.text }}</span>
  </div>
</template>
