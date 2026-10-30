<script setup lang="ts">
import { computed, ref } from 'vue';
import { QUESTION_MAX_LENGTH } from '@/constants/app';
import type { AnswerMode } from '@/types/api';
import ClearChatButton from './ClearChatButton.vue';

/**
 * ChatInput —— 输入区（F04）。
 *
 * 交互契约：
 *  - Enter 发送、Shift+Enter 换行
 *  - maxlength 1000（超长截断，不弹错）
 *  - 发送中禁用输入与按钮，给「停止」入口
 *  - 中文输入法组合期（isComposing）不触发发送 —— 这是最常见的误发来源
 */
const props = defineProps<{
  disabled?: boolean;
  streaming?: boolean;
  mode: AnswerMode;
  k: number;
}>();

const emit = defineEmits<{
  send: [string];
  stop: [];
  'update:mode': [AnswerMode];
  'update:k': [number];
  clear: [];
}>();

const text = ref('');
const composing = ref(false);

const trimmed = computed(() => text.value.trim());
const canSend = computed(() => !props.disabled && !props.streaming && trimmed.value.length > 0);

const modeOptions = [
  { value: 'rag' as AnswerMode, label: '查资料' },
  { value: 'direct' as AnswerMode, label: '直接答' },
  { value: 'both' as AnswerMode, label: '对照' },
];

const kOptions = [1, 2, 3, 4, 5];

function doSend(): void {
  if (!canSend.value) return;
  const q = trimmed.value;
  text.value = '';
  emit('send', q);
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key !== 'Enter') return;
  if (e.shiftKey) return; // Shift+Enter 换行
  if (composing.value || e.isComposing) return;
  e.preventDefault();
  doSend();
}

function onCompositionStart(): void {
  composing.value = true;
}

function onCompositionEnd(): void {
  composing.value = false;
}

/** 外部（示例问题 / 追问 chips）直接发送 */
function fillAndSend(q: string): void {
  if (props.disabled || props.streaming) return;
  text.value = '';
  emit('send', q);
}

defineExpose({ fillAndSend, text });
</script>

<template>
  <div class="composer" data-testid="chat-input">
    <div class="composer__row">
      <el-segmented
        :model-value="mode"
        :options="modeOptions"
        size="small"
        data-testid="mode-switch"
        @update:model-value="emit('update:mode', $event as AnswerMode)"
      />

      <label class="composer__k">
        <span class="composer__k-label">取回</span>
        <el-select
          :model-value="k"
          size="small"
          style="width: 68px"
          data-testid="k-select"
          @update:model-value="emit('update:k', Number($event))"
        >
          <el-option v-for="n in kOptions" :key="n" :label="String(n)" :value="n" />
        </el-select>
        <span class="composer__k-label">段</span>
      </label>

      <ClearChatButton
        class="composer__clear"
        :disabled="disabled || streaming"
        @confirm="emit('clear')"
      />
    </div>

    <div class="composer__box" :class="{ 'composer__box--busy': streaming }">
      <textarea
        v-model="text"
        class="composer__textarea"
        data-testid="question-input"
        :maxlength="QUESTION_MAX_LENGTH"
        :disabled="disabled"
        :aria-busy="streaming ? 'true' : 'false'"
        placeholder="输入问题，Enter 发送，Shift+Enter 换行"
        rows="3"
        @keydown="onKeydown"
        @compositionstart="onCompositionStart"
        @compositionend="onCompositionEnd"
      />
      <div class="composer__actions">
        <span class="composer__count">{{ text.length }} / {{ QUESTION_MAX_LENGTH }}</span>
        <button
          v-if="streaming"
          type="button"
          class="composer__stop"
          data-testid="chat-stop"
          @click="emit('stop')"
        >
          停止
        </button>
        <button
          v-else
          type="button"
          class="composer__send"
          data-testid="chat-send"
          :disabled="!canSend"
          @click="doSend"
        >
          发送
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.composer {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 20px 16px;
  border-top: 1px solid var(--line);
  background: var(--paper);
}

.composer__row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.composer__k {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--muted);
}

.composer__k-label {
  white-space: nowrap;
}

.composer__clear {
  margin-left: auto;
}

.composer__box {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg);
  transition: border-color 0.15s;
}

.composer__box:focus-within {
  border-color: var(--teal);
}

.composer__box--busy {
  border-color: color-mix(in srgb, var(--teal) 40%, transparent);
}

.composer__textarea {
  width: 100%;
  padding: 10px 12px;
  border: 0;
  background: transparent;
  color: var(--text);
  font-family: inherit;
  font-size: 14px;
  line-height: 1.6;
  resize: vertical;
  outline: none;
}

.composer__actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 0 12px 10px;
}

.composer__count {
  margin-right: auto;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--muted);
}

.composer__send,
.composer__stop {
  padding: 5px 16px;
  font-size: 13px;
  font-weight: 600;
  color: var(--paper);
  background: var(--teal);
  border: 0;
  border-radius: 8px;
  cursor: pointer;
}

.composer__send:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.composer__stop {
  background: var(--red);
}
</style>
