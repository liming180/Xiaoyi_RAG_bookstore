<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import type { AnswerMode, Citation, Message } from '@/types/api';
import { useConversationsStore } from '@/stores/conversations';
import { useQueryPrefs } from '@/composables/useQueryPrefs';
import { useConversation } from '../composables/useConversation';
import { useChat } from '../composables/useChat';
import MessageList from '../components/MessageList.vue';
import ChatInput from '../components/ChatInput.vue';
import RetrievalTrace from '../components/RetrievalTrace.vue';

/**
 * ChatView —— 对话页（P3-B：接上 SSE 发送链路）。
 *
 * 数据流：
 *   ChatInput.send → useChat.send → SSE 事件 → chatMachine（纯函数）
 *   → streamingMessage（流式占位）→ done 后 onPersist 落进 messages
 */
const route = useRoute();
const router = useRouter();
const conversations = useConversationsStore();
const { mode, k, setMode, setK } = useQueryPrefs();

const conversationId = computed<string | null>(() => {
  const param = route.params.id;
  if (typeof param === 'string' && param) return param;
  return conversations.activeId;
});

const { messages, loading, error, append, lastQuestion } = useConversation(
  () => conversationId.value,
);

const chat = useChat({
  conversationId: () => conversationId.value,
  onPersist: (message) => {
    // 流式版只是 streamingMessage（不在 messages 里），落库后直接追加真实消息
    append(message);
  },
});

const inputRef = ref<InstanceType<typeof ChatInput> | null>(null);
const traceForLast = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    const m = messages.value[i];
    if (m && m.role === 'assistant' && m.trace) return m.trace;
  }
  return null;
});

async function send(text: string): Promise<void> {
  if (!conversationId.value) return;
  // 用户气泡先进列表，视觉上立刻有反馈
  append({
    id: `local-u-${Date.now()}`,
    conversationId: conversationId.value,
    role: 'user',
    content: text,
    createdAt: Date.now(),
    citations: [],
    trace: null,
    usage: null,
    elapsedMs: null,
    degraded: false,
    suggestions: [],
    feedback: null,
  });
  await chat.send(text, mode.value, k.value);
}

/** 错误气泡上的重试：重发上一个问题 */
async function retry(): Promise<void> {
  const q = chat.question.value || lastQuestion.value;
  if (q) await send(q);
}

function onMode(value: AnswerMode): void {
  setMode(value);
}

function onK(value: number): void {
  setK(value);
}

function onOpenInKnowledge(citation: Citation): void {
  void router.push({
    name: 'chunks',
    query: { chunk_id: citation.chunkId, doc: citation.docTitle },
  });
}

/** 流式期间把临时消息塞给列表 */
const streaming = computed<Message | null>(() => chat.streamingMessage.value);

watch(
  () => chat.state.value.phase,
  (phase) => {
    if (phase === 'error' && chat.state.value.error) {
      append({
        id: `local-err-${Date.now()}`,
        conversationId: conversationId.value ?? '',
        role: 'assistant',
        content: chat.draft.value,
        createdAt: Date.now(),
        citations: chat.citations.value,
        trace: null,
        usage: null,
        elapsedMs: null,
        degraded: false,
        suggestions: [],
        feedback: null,
        error: chat.state.value.error.message,
      });
    }
  },
);
</script>

<template>
  <section class="chat-view" data-testid="page-chat">
    <div v-if="loading" class="chat-view__state" data-testid="chat-loading">正在加载对话…</div>
    <div v-else-if="error" class="chat-view__state chat-view__state--error" data-testid="chat-error">
      {{ error }}
    </div>

    <template v-else>
      <MessageList
        :messages="messages"
        :streaming="streaming"
        :pending-label="chat.pending.value"
        @retry="retry"
        @open-in-knowledge="onOpenInKnowledge"
      />

      <RetrievalTrace v-if="traceForLast" :trace="traceForLast" />

      <ChatInput
        ref="inputRef"
        :mode="mode"
        :k="k"
        :streaming="chat.isStreaming.value"
        @send="send"
        @stop="chat.stop()"
        @update:mode="onMode"
        @update:k="onK"
      />
    </template>
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
