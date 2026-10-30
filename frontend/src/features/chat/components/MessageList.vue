<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import type { Citation, Message } from '@/types/api';
import CitationCard from './CitationCard.vue';
import MessageBubble from './MessageBubble.vue';

/**
 * MessageList —— 对话流（F04）。
 *
 * 职责：
 *  - 渲染消息气泡，保持「用户右 / 助手左」
 *  - 管理引用卡的开合与定位高亮（点徽标 → 滚动到对应卡片并描边）
 *  - 新消息自动滚到底部
 */
const props = defineProps<{
  messages: Message[];
  /** 正在流式输出中的临时消息（尚未落库） */
  streaming?: Message | null;
  /** 当前阶段文案（P3-B 用，P3-A 传空） */
  pendingLabel?: string;
}>();

const emit = defineEmits<{
  cite: [Citation];
  retry: [];
  suggest: [string];
  openInKnowledge: [Citation];
}>();

const listEl = ref<HTMLElement | null>(null);
const activeCitation = ref<Citation | null>(null);
const activeQuestion = ref<string>('');

const visible = computed<Message[]>(() => {
  const base = props.messages.slice();
  if (props.streaming) base.push(props.streaming);
  return base;
});

/** 每条助手消息对应的提问（用于引用卡摘录高亮） */
const questionByMessage = computed(() => {
  const map = new Map<string, string>();
  let lastQuestion = '';
  for (const m of props.messages) {
    if (m.role === 'user') lastQuestion = m.content;
    else map.set(m.id, lastQuestion);
  }
  return map;
});

function onCite(citation: Citation): void {
  activeCitation.value = citation;
  emit('cite', citation);
  void nextTick(() => {
    const el = listEl.value?.querySelector<HTMLElement>(
      `[data-testid="cite-card-${String(citation.ref)}"]`,
    );
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  });
}

function closeCard(): void {
  activeCitation.value = null;
}

async function scrollToBottom(): Promise<void> {
  await nextTick();
  const el = listEl.value;
  if (el) el.scrollTop = el.scrollHeight;
}

watch(
  () => [visible.value.length, props.streaming?.content.length],
  () => void scrollToBottom(),
);

defineExpose({ scrollToBottom, onCite, closeCard, activeCitation });
</script>

<template>
  <div class="msg-list" ref="listEl" data-testid="message-list" role="log" aria-live="polite">
    <div v-if="visible.length === 0" class="msg-list__empty" data-testid="message-empty">
      <p class="msg-list__empty-title">还没有对话</p>
      <p class="msg-list__empty-hint">在下面输入问题，或点一个示例问题开始。</p>
    </div>

    <MessageBubble
      v-for="m in visible"
      :key="m.id"
      :message="m"
      :question="questionByMessage.get(m.id) ?? activeQuestion"
      @cite="onCite"
      @retry="emit('retry')"
      @suggest="emit('suggest', $event)"
    />

    <div v-if="pendingLabel" class="msg-list__pending" data-testid="msg-pending" aria-busy="true">
      <span class="msg-list__spinner" aria-hidden="true" />
      <span>{{ pendingLabel }}</span>
    </div>

    <div v-if="activeCitation" class="msg-list__card-wrap" data-testid="cite-card-wrap">
      <CitationCard
        :citation="activeCitation"
        :question="activeQuestion"
        :active="true"
        @close="closeCard"
        @open-in-knowledge="emit('openInKnowledge', $event)"
      />
    </div>
  </div>
</template>

<style scoped>
.msg-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  flex: 1;
  min-height: 0;
  padding: 18px 20px;
  overflow-y: auto;
  background: var(--bg);
}

.msg-list__empty {
  margin: auto;
  text-align: center;
  color: var(--muted);
}

.msg-list__empty-title {
  margin: 0 0 6px;
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
}

.msg-list__empty-hint {
  margin: 0;
  font-size: 13px;
}

.msg-list__pending {
  display: flex;
  align-items: center;
  gap: 8px;
  align-self: flex-start;
  padding: 8px 14px;
  font-size: 13px;
  color: var(--teal);
  background: var(--soft);
  border-radius: 999px;
}

.msg-list__spinner {
  width: 12px;
  height: 12px;
  border: 2px solid color-mix(in srgb, var(--teal) 30%, transparent);
  border-top-color: var(--teal);
  border-radius: 50%;
  animation: msg-spin 0.8s linear infinite;
}

@keyframes msg-spin {
  to {
    transform: rotate(360deg);
  }
}

.msg-list__card-wrap {
  position: sticky;
  bottom: 0;
  align-self: stretch;
  z-index: 3;
}
</style>
