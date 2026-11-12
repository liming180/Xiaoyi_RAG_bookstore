<script setup lang="ts">
import { computed } from 'vue';
import { useSystemStatusStore } from '@/stores/systemStatus';

/**
 * 状态灯（F03）：三色 + tooltip。
 * 绿 = 已就绪；黄 = 资料待更新（可提问但结果基于旧库）；红 = 不可用（仅直接模式）。
 */
const store = useSystemStatusStore();

const tooltip = computed(() => {
  const d = store.detail;
  if (store.degradedBySse) return 'AI 服务暂时降级，回答可能不完整';
  if (store.status === 'ready') {
    return d ? `已就绪 · ${d.docCount} 份资料 / ${d.chunkCount} 片段` : '已就绪';
  }
  if (store.status === 'needs_rebuild') {
    return d?.reason ? `资料待更新：${d.reason}` : '资料或分块设置已改变，需重新建库';
  }
  return store.lastError ? `知识库不可用：${store.lastError}` : '知识库暂不可用，仅直接模式可用';
});
</script>

<template>
  <el-tooltip :content="tooltip" placement="bottom" effect="dark">
    <span class="status-light" :class="`status-light--${store.tone}`" data-testid="status-light">
      <span class="status-light__dot" aria-hidden="true" />
      <span class="status-light__text">{{ store.label }}</span>
    </span>
  </el-tooltip>
</template>

<style scoped>
.status-light {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  border: 1px solid var(--line);
  background: var(--paper);
  cursor: default;
  white-space: nowrap;
}

.status-light__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--muted);
}

.status-light--ok .status-light__dot {
  background: var(--teal);
  box-shadow: 0 0 0 3px var(--soft);
}

.status-light--ok .status-light__text {
  color: var(--teal-dark);
}

.status-light--warn .status-light__dot {
  background: var(--amber);
  box-shadow: 0 0 0 3px var(--amber-soft);
}

.status-light--warn .status-light__text {
  color: var(--amber);
}

.status-light--error .status-light__dot {
  background: var(--red);
  box-shadow: 0 0 0 3px var(--red-soft);
}

.status-light--error .status-light__text {
  color: var(--red);
}
</style>
