<script setup lang="ts">
import { computed, ref } from 'vue';
import { ElMessage } from 'element-plus';
import type { FeedbackRating } from '@/types/api';
import { evalApi } from '@/api';

/**
 * FeedbackBar —— 回答反馈闭环（套餐 C1）。
 *
 * 契约：
 *  - 每条助手回答 👍/👎，hover 才显形（避免视觉噪声）
 *  - 👎 展开原因标签（答错/没找到/来源不符/其他），提交后 toast
 *  - 同一消息重复反馈只保留最新（后端覆盖，前端以后端回传为准）
 *  - 提交成功即固化高亮；失败回滚到上一态并提示
 *
 * 注意：这里不写 store —— 反馈状态属于单条消息，跟着消息对象走。
 */
const props = defineProps<{
  messageId: string;
  /** 服务端已记录的反馈（刷新后仍在） */
  modelValue?: FeedbackRating | null;
  disabled?: boolean;
}>();

const emit = defineEmits<{ 'update:modelValue': [FeedbackRating | null] }>();

const TAGS = [
  { value: 'wrong', label: '答错' },
  { value: 'missing', label: '没找到' },
  { value: 'source', label: '来源不符' },
  { value: 'other', label: '其他' },
] as const;

const current = ref<FeedbackRating | null>(props.modelValue ?? null);
const tagOpen = ref(false);
const picked = ref<string[]>([]);
const busy = ref(false);

const downActive = computed(() => current.value === 'down');
const upActive = computed(() => current.value === 'up');

async function submit(rating: FeedbackRating, tags: string[] = []): Promise<void> {
  if (props.disabled || busy.value) return;
  const prev = current.value;
  busy.value = true;
  current.value = rating;
  try {
    await evalApi.submitFeedback(props.messageId, {
      rating,
      tags: tags.length > 0 ? tags : undefined,
    });
    emit('update:modelValue', rating);
    ElMessage.success('已记录，将用于改进评测');
  } catch (e) {
    current.value = prev;
    ElMessage.error(e instanceof Error ? e.message : '反馈提交失败，请重试');
  } finally {
    busy.value = false;
  }
}

function onUp(): void {
  void submit('up');
}

function onDown(): void {
  if (props.disabled || busy.value) return;
  // 展开标签面板；未选标签时先记一条裸 down，标签补选后再覆盖
  tagOpen.value = true;
  if (current.value !== 'down') void submit('down');
}

function toggleTag(value: string): void {
  const i = picked.value.indexOf(value);
  if (i >= 0) picked.value.splice(i, 1);
  else picked.value.push(value);
}

async function confirmTags(): Promise<void> {
  await submit('down', picked.value);
  tagOpen.value = false;
  picked.value = [];
}
</script>

<template>
  <div class="fb" data-testid="feedback-bar" :data-message-id="messageId">
    <button
      type="button"
      class="fb__btn"
      :class="{ 'fb__btn--active': upActive }"
      data-testid="feedback-up"
      :aria-pressed="upActive"
      :disabled="disabled || busy"
      title="这条回答有帮助"
      @click="onUp"
    >
      👍
    </button>
    <button
      type="button"
      class="fb__btn"
      :class="{ 'fb__btn--active fb__btn--down': downActive }"
      data-testid="feedback-down"
      :aria-pressed="downActive"
      :disabled="disabled || busy"
      title="这条回答有问题"
      @click="onDown"
    >
      👎
    </button>

    <div v-if="tagOpen" class="fb__tags" data-testid="feedback-tags">
      <button
        v-for="t in TAGS"
        :key="t.value"
        type="button"
        class="fb__tag"
        :class="{ 'fb__tag--on': picked.includes(t.value) }"
        :data-testid="`feedback-tag-${t.value}`"
        @click="toggleTag(t.value)"
      >
        {{ t.label }}
      </button>
      <button type="button" class="fb__ok" data-testid="feedback-tag-confirm" @click="confirmTags">
        提交
      </button>
    </div>
  </div>
</template>

<style scoped>
.fb {
  position: relative;
  display: flex;
  align-items: center;
  gap: 4px;
  opacity: 0.35;
  transition: opacity 0.15s ease;
}

.fb:hover,
.fb:focus-within {
  opacity: 1;
}

.fb__btn {
  padding: 2px 6px;
  font-size: 13px;
  line-height: 1.2;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  cursor: pointer;
  filter: grayscale(1);
}

.fb__btn:hover:not(:disabled) {
  border-color: var(--line);
}

.fb__btn--active {
  filter: none;
  background: var(--soft);
  border-color: var(--teal);
}

.fb__btn--down {
  background: var(--red-soft);
  border-color: var(--red);
}

.fb__btn:disabled {
  cursor: not-allowed;
}

.fb__tags {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 0;
  z-index: 5;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 6px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow);
}

.fb__tag {
  padding: 2px 8px;
  font-size: 11px;
  color: var(--muted);
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 999px;
  cursor: pointer;
}

.fb__tag--on {
  color: var(--teal-dark);
  background: var(--soft);
  border-color: var(--teal);
}

.fb__ok {
  padding: 2px 8px;
  font-size: 11px;
  color: var(--paper);
  background: var(--teal);
  border: none;
  border-radius: 999px;
  cursor: pointer;
}
</style>
