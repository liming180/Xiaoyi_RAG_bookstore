<script setup lang="ts">
import { computed } from 'vue';
import { useSystemStatusStore } from '@/stores/systemStatus';

/**
 * 参数实验互斥横幅（套餐 E3）。
 *
 * 为什么单独一个组件而不是塞进 StatusBanner：两者的可见条件完全正交
 * （状态灯管知识库健康度，这里管实验占用），混在一起会让「知识库就绪但实验在跑」
 * 这类组合无法表达 —— 而那正是 E3 的典型状态。
 *
 * 数据来源是 `systemStatus.experimentRunning`，由 `emit('experiment:running')`
 * 统一驱动，因此对话页输入框的禁用态与本横幅永远同步。
 */
const store = useSystemStatusStore();

const visible = computed(() => store.experimentRunning);
</script>

<template>
  <div v-if="visible" class="exp-banner" data-testid="experiment-banner" role="status">
    <span class="exp-banner__dot" aria-hidden="true" />
    <span class="exp-banner__text">
      参数实验进行中，提问暂不可用（后端 409 互斥保护）。实验完成后自动恢复。
    </span>
    <span class="exp-banner__hint">可在「评测 → 参数实验」查看进度</span>
  </div>
</template>

<style scoped>
.exp-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  font-size: 13px;
  color: var(--teal-dark);
  background: color-mix(in srgb, var(--teal) 10%, var(--paper));
  border-bottom: 1px solid color-mix(in srgb, var(--teal) 28%, var(--line));
}

.exp-banner__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--teal);
  flex-shrink: 0;
  animation: exp-pulse 1.4s ease-in-out infinite;
}

.exp-banner__text {
  flex: 1;
  min-width: 0;
}

.exp-banner__hint {
  font-size: 12px;
  color: var(--muted);
  flex-shrink: 0;
}

@keyframes exp-pulse {
  0%,
  100% {
    opacity: 0.35;
  }
  50% {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .exp-banner__dot {
    animation: none;
  }
}
</style>
