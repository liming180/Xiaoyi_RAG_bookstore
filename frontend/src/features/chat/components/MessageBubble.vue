<script setup lang="ts">
import { computed } from 'vue';
import type { Citation, FeedbackRating, Message } from '@/types/api';
import AnswerBody from './AnswerBody.vue';
import FeedbackBar from './FeedbackBar.vue';

/**
 * MessageBubble —— 单条消息气泡（F04/F05/F11）。
 *
 * 用户气泡纯文本；助手气泡渲染结构化回答 + 引用徽标 + 元信息（耗时/降级/未核实提醒）。
 * 用户输入同样只走文本插值，永不 v-html。
 */
const props = defineProps<{
  message: Message;
  /** 触发这条回答的问题，用于引用卡摘录高亮 */
  question?: string;
}>();

const emit = defineEmits<{
  cite: [Citation];
  retry: [];
  suggest: [string];
  feedback: [string, FeedbackRating | null];
}>();

const isUser = computed(() => props.message.role === 'user');

const hasUnverified = computed(
  () => !isUser.value && props.message.citations.some((c) => !c.verified),
);

const elapsedText = computed(() => {
  const ms = props.message.elapsedMs;
  if (ms === null || ms === undefined || ms <= 0) return '';
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
});

const timeText = computed(() => {
  const ts = props.message.createdAt;
  if (!ts) return '';
  const d = new Date(ts);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${hh}:${mm}`;
});

const suggestions = computed(() => (props.message.suggestions ?? []).slice(0, 3));

/** 反馈状态上抛，由页面层写回消息对象（组件内不改 prop） */
function onFeedback(rating: FeedbackRating | null): void {
  emit('feedback', props.message.id, rating);
}
</script>

<template>
  <div
    class="bubble"
    :class="isUser ? 'bubble--user' : 'bubble--assistant'"
    :data-testid="isUser ? 'msg-user' : 'msg-assistant'"
    :data-message-id="message.id"
  >
    <div class="bubble__meta-top" v-if="!isUser">
      <span class="bubble__role">助手</span>
      <span v-if="timeText" class="bubble__time">{{ timeText }}</span>
      <span v-if="elapsedText" class="bubble__elapsed" data-testid="msg-elapsed"
        >耗时 {{ elapsedText }}</span
      >
    </div>

    <div class="bubble__content">
      <p v-if="isUser" class="bubble__plain">{{ message.content }}</p>
      <AnswerBody
        v-else
        :content="message.content"
        :citations="message.citations"
        @cite="emit('cite', $event)"
      />
    </div>

    <!-- F11：本轮取回含未核实资料 -->
    <p v-if="hasUnverified" class="bubble__warn" data-testid="unverified-warn">
      本轮参考来源包含未经核实的资料，请谨慎对待相关内容。
    </p>

    <!-- done.degraded = true -->
    <p v-if="message.degraded" class="bubble__degraded" data-testid="msg-degraded">
      AI 服务降级：本次回答未使用检索资料，仅供参考。
    </p>

    <p v-if="message.error" class="bubble__error" data-testid="msg-error">
      {{ message.error }}
      <button type="button" class="bubble__retry" @click="emit('retry')">重试</button>
    </p>

    <!-- B1 追问推荐：缺失或空数组都不渲染 -->
    <div v-if="!isUser && suggestions.length > 0" class="bubble__chips" data-testid="msg-suggestions">
      <button
        v-for="(s, i) in suggestions"
        :key="i"
        type="button"
        class="bubble__chip"
        @click="emit('suggest', s)"
      >
        {{ s }}
      </button>
    </div>

    <!-- C1 反馈闭环：只对已落库的助手消息开放 -->
    <div v-if="!isUser && message.id !== 'streaming'" class="bubble__foot">
      <FeedbackBar
        :message-id="message.id"
        :model-value="message.feedback"
        :disabled="Boolean(message.error)"
        @update:model-value="onFeedback"
      />
    </div>
  </div>
</template>

<style scoped>
.bubble {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-width: min(760px, 88%);
  padding: 12px 14px;
  border-radius: var(--radius);
  font-size: 14px;
}

.bubble--user {
  align-self: flex-end;
  background: var(--teal);
  color: var(--paper);
}

.bubble--assistant {
  align-self: flex-start;
  background: var(--paper);
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
}

.bubble__meta-top {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--muted);
}

.bubble__role {
  font-weight: 600;
  color: var(--ink);
}

.bubble__elapsed {
  font-family: var(--font-mono);
}

.bubble__plain {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.7;
}

.bubble__warn {
  margin: 0;
  padding: 6px 10px;
  font-size: 12px;
  color: var(--amber);
  background: var(--amber-soft);
  border-radius: 8px;
}

.bubble__degraded {
  margin: 0;
  padding: 6px 10px;
  font-size: 12px;
  color: var(--amber);
  background: var(--amber-soft);
  border-radius: 8px;
}

.bubble__error {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 6px 10px;
  font-size: 12px;
  color: var(--red);
  background: var(--red-soft);
  border-radius: 8px;
}

.bubble__retry {
  margin-left: auto;
  padding: 2px 10px;
  font-size: 12px;
  color: var(--red);
  background: transparent;
  border: 1px solid currentColor;
  border-radius: 6px;
  cursor: pointer;
}

.bubble__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;
}

.bubble__chip {
  padding: 4px 10px;
  font-size: 12px;
  color: var(--teal);
  background: var(--soft);
  border: 1px solid transparent;
  border-radius: 999px;
  cursor: pointer;
}

.bubble__chip:hover {
  border-color: var(--teal);
}

.bubble__foot {
  display: flex;
  justify-content: flex-end;
  margin-top: 2px;
}
</style>
