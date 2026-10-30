<script setup lang="ts">
/**
 * SuggestionChips —— 示例问题（F04 空态引导）。
 *
 * 来自常量文件，不请求后端；点击即发送。
 * 一旦会话里有消息就隐藏，避免长期占位。
 */
defineProps<{
  items: string[];
  disabled?: boolean;
}>();

const emit = defineEmits<{ pick: [string] }>();
</script>

<template>
  <div v-if="items.length > 0" class="sugg" data-testid="suggestion-chips">
    <span class="sugg__label">试试问：</span>
    <button
      v-for="(item, i) in items"
      :key="i"
      type="button"
      class="sugg__chip"
      :disabled="disabled"
      @click="emit('pick', item)"
    >
      {{ item }}
    </button>
  </div>
</template>

<style scoped>
.sugg {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 20px 10px;
}

.sugg__label {
  font-size: 12px;
  color: var(--muted);
}

.sugg__chip {
  padding: 4px 10px;
  font-size: 12px;
  color: var(--text);
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 999px;
  cursor: pointer;
  transition:
    border-color 0.15s,
    color 0.15s;
}

.sugg__chip:hover:not(:disabled) {
  color: var(--teal);
  border-color: var(--teal);
}

.sugg__chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
