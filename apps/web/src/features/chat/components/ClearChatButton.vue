<script setup lang="ts">
import { ElMessageBox } from 'element-plus';

/**
 * ClearChatButton —— 清空对话（F10）。
 *
 * 契约：确认后清服务端消息、本地清空，**保留 mode/k**（这两个在 localStorage，
 * 不属于对话内容）。会话本身保留，不删会话。
 */
const props = defineProps<{ disabled?: boolean }>();
const emit = defineEmits<{ confirm: [] }>();

async function onClick(): Promise<void> {
  if (props.disabled) return;
  try {
    await ElMessageBox.confirm(
      '清空后本轮对话的消息将被删除，提问模式与取回数量会保留。',
      '清空对话',
      {
        confirmButtonText: '清空',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      },
    );
    emit('confirm');
  } catch {
    // 用户取消：不做任何事
  }
}
</script>

<template>
  <button
    type="button"
    class="clear-btn"
    data-testid="clear-chat"
    :disabled="disabled"
    @click="onClick"
  >
    清空对话
  </button>
</template>

<style scoped>
.clear-btn {
  padding: 3px 10px;
  font-size: 12px;
  color: var(--muted);
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 6px;
  cursor: pointer;
}

.clear-btn:hover:not(:disabled) {
  color: var(--red);
  border-color: var(--red);
}

.clear-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
