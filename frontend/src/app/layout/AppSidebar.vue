<script setup lang="ts">
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ChatDotRound, Collection, TrendCharts } from '@element-plus/icons-vue';

/**
 * 左侧导航：对话 / 知识库 / 评测。
 * 窄屏（<1080px）由 AppShell 收起为抽屉，这里只负责导航项本身。
 */
const route = useRoute();
const router = useRouter();

const items = [
  { name: 'chat', label: '对话', icon: ChatDotRound, testid: 'nav-chat' },
  { name: 'knowledge', label: '知识库', icon: Collection, testid: 'nav-knowledge' },
  { name: 'eval', label: '评测', icon: TrendCharts, testid: 'nav-eval' },
] as const;

const current = computed(() => (route.name as string) ?? 'chat');

function go(name: string): void {
  if (route.name !== name) void router.push({ name });
}
</script>

<template>
  <nav class="sidebar" aria-label="主导航" data-testid="app-sidebar">
    <button
      v-for="item in items"
      :key="item.name"
      type="button"
      class="sidebar__item"
      :class="{ 'sidebar__item--active': current === item.name }"
      :data-testid="item.testid"
      :aria-current="current === item.name ? 'page' : undefined"
      @click="go(item.name)"
    >
      <el-icon><component :is="item.icon" /></el-icon>
      <span>{{ item.label }}</span>
    </button>

    <div class="sidebar__footer">
      <slot name="footer" />
    </div>
  </nav>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: var(--sidebar-w);
  flex: 0 0 var(--sidebar-w);
  padding: 12px 8px;
  background: var(--sidebar);
  border-right: 1px solid var(--line);
  overflow-y: auto;
}

.sidebar__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text);
  font-size: 14px;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.sidebar__item:hover {
  background: var(--soft);
}

.sidebar__item--active {
  background: var(--paper);
  color: var(--teal-dark);
  font-weight: 600;
  box-shadow: var(--shadow);
}

.sidebar__footer {
  margin-top: auto;
  padding-top: 12px;
}
</style>
