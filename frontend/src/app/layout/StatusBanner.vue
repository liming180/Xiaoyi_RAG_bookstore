<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { useSystemStatusStore } from '@/stores/systemStatus';

/**
 * 全站状态横幅（F03）。
 *
 * - needs_rebuild：琥珀色，提示结果基于旧知识库，并给「重新建库」直达入口
 * - unavailable：红色，说明仅直接模式可用
 * - ready：不渲染
 */
const store = useSystemStatusStore();
const router = useRouter();

const visible = computed(() => store.status !== 'ready' || store.degradedBySse);

const tone = computed(() => (store.status === 'unavailable' ? 'error' : 'warn'));

const text = computed(() => {
  if (store.degradedBySse) return 'AI 服务暂时降级，已切换为直接回答模式，回答可能不完整。';
  if (store.status === 'needs_rebuild') {
    return '资料或分块设置已改变，重新建库后即可使用最新资料提问。';
  }
  return '知识库暂不可用，当前仅「直接答」模式可用。';
});

function goRebuild(): void {
  void router.push({ name: 'knowledge', query: { focus: 'build' } });
}
</script>

<template>
  <div v-if="visible" class="status-banner" :class="`status-banner--${tone}`" data-testid="status-banner">
    <span class="status-banner__text">{{ text }}</span>
    <el-button
      v-if="store.status === 'needs_rebuild'"
      size="small"
      type="warning"
      plain
      data-testid="banner-rebuild"
      @click="goRebuild"
    >
      重新建库
    </el-button>
    <el-button v-else-if="store.status === 'unavailable'" size="small" plain @click="store.refresh()">
      重试
    </el-button>
  </div>
</template>

<style scoped>
.status-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 16px;
  font-size: 13px;
  border-bottom: 1px solid var(--line);
}

.status-banner--warn {
  background: var(--amber-soft);
  color: var(--amber);
}

.status-banner--error {
  background: var(--red-soft);
  color: var(--red);
}

.status-banner__text {
  flex: 1;
  min-width: 0;
}
</style>
