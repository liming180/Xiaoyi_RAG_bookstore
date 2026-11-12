<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import type { Citation, Message } from '@/types/api';
import CitationCard from './CitationCard.vue';
import MessageBubble from './MessageBubble.vue';
import LatticeLoader from '@/components/bits/LatticeLoader.vue';

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
  /**
   * 对照模式下隐藏最后一轮的助手气泡。
   *
   * <p>为什么要藏：对照模式的两栏已经把这一轮的回答完整显示了（且是并排的、
   * 带差异摘要的），再在上方渲染一个普通气泡就是同一段内容的第二份拷贝。
   * 实测截图里用户要同时看两处基本相同的内容，得来回滚动才能对上。
   *
   * <p>只藏**最后一轮**：更早的轮次仍按普通气泡显示，否则历史对话会整段消失。
   */
  hideAssistantInCompare?: boolean;
}>();

const emit = defineEmits<{
  cite: [Citation];
  retry: [];
  suggest: [string];
  openInKnowledge: [Citation];
  feedback: [string, 'up' | 'down' | null];
}>();

const listEl = ref<HTMLElement | null>(null);
const activeCitation = ref<Citation | null>(null);
const activeQuestion = ref<string>('');

/**
 * 最后一条 user 消息之后的所有 assistant 消息。
 *
 * 对照模式要藏掉的就是它们：这些属于「当前这一轮」，已经被两栏完整覆盖。
 */
const lastTurnAssistantIds = computed(() => {
  if (!props.hideAssistantInCompare) return new Set<string>();
  let lastUserIndex = -1;
  for (let i = props.messages.length - 1; i >= 0; i -= 1) {
    if (props.messages[i]?.role === 'user') {
      lastUserIndex = i;
      break;
    }
  }
  if (lastUserIndex < 0) return new Set<string>();
  const ids = new Set<string>();
  for (let i = lastUserIndex + 1; i < props.messages.length; i += 1) {
    const m = props.messages[i];
    if (m && m.role === 'assistant') ids.add(m.id);
  }
  return ids;
});

const visible = computed<Message[]>(() => {
  const base = props.messages.filter((m) => !lastTurnAssistantIds.value.has(m.id));
  // 流式占位在对照模式下同样由两栏承载，不再单独塞气泡。
  if (props.streaming && !props.hideAssistantInCompare) base.push(props.streaming);
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
      @feedback="(id, rating) => emit('feedback', id, rating)"
    />

    <div v-if="pendingLabel" class="msg-list__pending" data-testid="msg-pending" aria-busy="true">
      <LatticeLoader
        class="msg-list__lattice"
        :label="pendingLabel"
        pattern="orbit"
        :grid="3"
        shape="round"
        :cell-size="5"
        :gap="2"
        :font-size="13"
        :idle-opacity="0.15"
        :glow="false"
        :show-timer="true"
        color="var(--teal)"
      />
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
  padding: 6px 14px;
  background: var(--soft);
  border-radius: 999px;
  color: var(--teal);
}

/* LatticeLoader（vue-bits）等待行：格子 + 阶段文案 + 计时 */
.msg-list__lattice {
  color: var(--teal);
}

.msg-list__card-wrap {
  position: sticky;
  bottom: 0;
  align-self: stretch;
  z-index: 3;
}
</style>
