<script setup lang="ts">
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import type { Citation } from '@/types/api';
import { useConversationsStore } from '@/stores/conversations';
import { useConversation } from '../composables/useConversation';
import MessageList from '../components/MessageList.vue';

/**
 * ChatView —— 对话页（P3-A 版本：只读渲染 + 引用卡）。
 *
 * P3-B 会在这里接上 SSE 发送链路，P3-C 接上模式/k/清空。
 */
const route = useRoute();
const router = useRouter();
const conversations = useConversationsStore();

const conversationId = computed<string | null>(() => {
  const param = route.params.id;
  if (typeof param === 'string' && param) return param;
  return conversations.activeId;
});

const { messages, loading, error } = useConversation(() => conversationId.value);

function onOpenInKnowledge(citation: Citation): void {
  void router.push({
    name: 'chunks',
    query: { chunk_id: citation.chunkId, doc: citation.docTitle },
  });
}
</script>

<template>
  <section class="chat-view" data-testid="page-chat">
    <div v-if="loading" class="chat-view__state" data-testid="chat-loading">正在加载对话…</div>
    <div v-else-if="error" class="chat-view__state chat-view__state--error" data-testid="chat-error">
      {{ error }}
    </div>
    <MessageList
      v-else
      :messages="messages"
      @open-in-knowledge="onOpenInKnowledge"
    />
  </section>
</template>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.chat-view__state {
  padding: 24px;
  color: var(--muted);
  font-size: 13px;
}

.chat-view__state--error {
  color: var(--red);
}
</style>
