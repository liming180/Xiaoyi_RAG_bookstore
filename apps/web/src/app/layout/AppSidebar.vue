<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { ChatDotRound, Collection, Setting, TrendCharts } from '@element-plus/icons-vue';
import { isAdmin } from '@/app/router/role';
import { useConversationsStore } from '@/stores/conversations';

/**
 * 左侧导航：对话 / 知识库 / 评测 + 最近会话列表。
 *
 * 窄屏（<1080px）由 AppShell 收起为抽屉，这里只负责导航项本身。
 *
 * 换肤改动（2026-11-09）：新增「最近会话」分区。
 * 原方案会话只藏在顶栏的下拉框里，切换一次要点两下（展开 + 选中）；
 * 侧栏有 272px 高度基本闲置，把会话列表放进来之后切会话只需一次点击。
 * 顶栏下拉保留（作为窄屏与键盘入口），两者共享同一个 store，状态不会分叉。
 */
const route = useRoute();
const router = useRouter();
const conversations = useConversationsStore();

const items = computed(() => {
  const base = [
    { name: 'chat', label: '对话', icon: ChatDotRound, testid: 'nav-chat' },
    { name: 'knowledge', label: '知识库', icon: Collection, testid: 'nav-knowledge' },
    { name: 'eval', label: '评测', icon: TrendCharts, testid: 'nav-eval' },
  ];
  // 管理端入口只给 ADMIN：普通用户看不到，手输 URL 也会被 adminGuard 弹回对话页。
  if (isAdmin()) {
    base.push({ name: 'admin-users', label: '管理端', icon: Setting, testid: 'nav-admin' });
  }
  return base;
});

const current = computed(() => (route.name as string) ?? 'chat');

/** 会话按更新时间倒序，最多显示 12 条 —— 再多就失去「最近」的意义 */
const recent = computed(() =>
  [...conversations.list]
    .sort((a, b) => (b.updatedAt ?? b.createdAt ?? 0) - (a.updatedAt ?? a.createdAt ?? 0))
    .slice(0, 12),
);

function go(name: string): void {
  if (route.name !== name) void router.push({ name });
}

/**
 * 切会话：设置 active 并跳到对话页。
 *
 * 与顶栏下拉的行为保持一致（AppTopbar 的 activeId setter 也是这两步），
 * 否则会出现「侧栏点了但页面还在知识库」的分叉。
 */
function openConv(id: string): void {
  conversations.setActive(id);
  if (route.name !== 'chat') void router.push({ name: 'chat' });
}

async function onCreate(): Promise<void> {
  const conv = await conversations.create();
  if (conv && route.name !== 'chat') void router.push({ name: 'chat' });
}

/** 正在删除的会话 id —— 用它在列表里显示「删除中」并禁掉重复点击 */
const removing = ref<string | null>(null);

/**
 * 删除会话（与主流 AI 聊天一致：悬停出现删除图标 → 二次确认 → 列表移除）。
 *
 * 三个必须处理干净的边界：
 *  1. **删的是当前会话**：store.remove 会把 activeId 切到列表第一条，
 *     但路由上的 :id 还是旧的 —— 不主动 replace 就会停在已删除会话的 URL 上，
 *     刷新一次就 404。所以删完要 replace 到新的 activeId（或裸 /chat）。
 *  2. **删的是最后一条**：activeId 变 null，跳到 /chat 空态。
 *  3. **删除失败**：不能把条目从列表里抹掉（store 里先调接口再改本地，
 *     接口抛错时本地列表不变），这里只提示，不做乐观移除。
 */
async function onRemoveConv(id: string, title: string): Promise<void> {
  if (removing.value) return;
  try {
    await ElMessageBox.confirm(
      `删除后「${title || id}」的消息将无法恢复。`,
      '删除会话',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      },
    );
  } catch {
    return; // 用户取消
  }

  const wasActive = conversations.activeId === id;
  removing.value = id;
  try {
    await conversations.remove(id);
    ElMessage.success('会话已删除');
    if (wasActive) {
      const next = conversations.activeId;
      await router.replace(next ? { name: 'chat', params: { id: next } } : { name: 'chat' });
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '删除失败，请重试');
  } finally {
    removing.value = null;
  }
}

/**
 * 时间显示：后端给的是 Unix 秒，统一用 toMillis 归一化。
 * （这里内联是因为 utils/time.ts 尚无该模块 —— 步骤 4 会抽公共函数并替换。）
 */
function timeText(ts: number | null | undefined): string {
  if (!ts) return '';
  const ms = ts < 1e11 ? ts * 1000 : ts;
  const diff = Date.now() - ms;
  const m = Math.round(diff / 60000);
  if (m < 1) return '刚刚';
  if (m < 60) return `${m} 分钟前`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.round(h / 24)} 天前`;
}
</script>

<template>
  <nav class="sidebar" aria-label="主导航" data-testid="app-sidebar">
    <div class="sidebar__nav">
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
    </div>

    <div class="sidebar__div">
      <span class="sidebar__label">最近会话</span>
      <button
        type="button"
        class="sidebar__add"
        title="新建会话"
        data-testid="sidebar-new-conv"
        @click="onCreate"
      >
        +
      </button>
    </div>

    <div class="convs" data-testid="sidebar-conv-list">
      <p v-if="recent.length === 0" class="convs__empty">还没有会话</p>
      <div
        v-for="conv in recent"
        :key="conv.id"
        class="conv"
        :class="{
          'conv--active': conversations.activeId === conv.id,
          'conv--removing': removing === conv.id,
        }"
        :data-testid="`sidebar-conv-${conv.id}`"
        :title="conv.title || conv.id"
        role="button"
        tabindex="0"
        @click="openConv(conv.id)"
        @keydown.enter.prevent="openConv(conv.id)"
        @keydown.space.prevent="openConv(conv.id)"
      >
        <span class="conv__title">{{ conv.title || conv.id }}</span>
        <span class="conv__meta">
          <span>{{ timeText(conv.updatedAt ?? conv.createdAt) }}</span>
          <span v-if="conv.messageCount" class="conv__dot" />
          <span v-if="conv.messageCount">{{ conv.messageCount }} 条</span>
        </span>
        <button
          type="button"
          class="conv__del"
          :disabled="removing === conv.id"
          :aria-label="`删除会话 ${conv.title || conv.id}`"
          :data-testid="`sidebar-conv-del-${conv.id}`"
          title="删除会话"
          @click.stop="onRemoveConv(conv.id, conv.title)"
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
          >
            <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6" />
          </svg>
        </button>
      </div>
    </div>

    <div class="sidebar__footer">
      <slot name="footer" />
    </div>
  </nav>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  width: var(--sidebar-w);
  flex: 0 0 var(--sidebar-w);
  background: var(--sidebar);
  border-right: 1px solid var(--line);
  overflow: hidden;
}

.sidebar__nav {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: var(--s3) var(--s2) var(--s2);
}

.sidebar__item {
  display: flex;
  align-items: center;
  gap: var(--s2);
  padding: 7px var(--s3);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition:
    background 0.15s var(--ease),
    color 0.15s var(--ease);
}

.sidebar__item:hover {
  background: var(--hover);
}

.sidebar__item--active {
  background: var(--paper);
  color: var(--ink);
  font-weight: 600;
  box-shadow: var(--shadow-xs);
}

.sidebar__item--active :deep(.el-icon) {
  color: var(--teal);
}

.sidebar__div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--s3) var(--s4) var(--s2);
}

.sidebar__label {
  font-size: 11px;
  font-weight: 600;
  color: var(--faint);
  letter-spacing: 0.04em;
}

.sidebar__add {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  padding: 0;
  font-size: 15px;
  line-height: 1;
  color: var(--muted);
  background: transparent;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
}

.sidebar__add:hover {
  color: var(--teal);
  background: var(--soft);
}

.convs {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 var(--s2) var(--s2);
}

.convs__empty {
  margin: 0;
  padding: var(--s3);
  font-size: 12px;
  color: var(--faint);
  text-align: center;
}

.conv {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 1px;
  width: 100%;
  margin-bottom: 1px;
  padding: 7px var(--s3);
  /* 右侧留出删除按钮的位置，避免标题被图标压住 */
  padding-right: 30px;
  text-align: left;
  background: transparent;
  border: 0;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background 0.15s var(--ease);
}

.conv:focus-visible {
  outline: 2px solid var(--teal);
  outline-offset: -2px;
}

/*
 * 删除按钮：默认隐形，悬停 / 键盘聚焦 / 当前会话时出现。
 * 用 opacity 而不是 display —— display 切换会让按钮在指针移入瞬间改变布局，
 * 列表条目高度抖动一下；opacity 保持布局稳定，也只对可交互元素生效。
 */
.conv__del {
  position: absolute;
  top: 50%;
  right: 6px;
  transform: translateY(-50%);
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  padding: 0;
  color: var(--faint);
  background: transparent;
  border: 0;
  border-radius: 5px;
  cursor: pointer;
  opacity: 0;
  transition:
    opacity 0.15s var(--ease),
    color 0.15s var(--ease),
    background 0.15s var(--ease);
}

.conv:hover .conv__del,
.conv:focus-within .conv__del,
.conv--active .conv__del {
  opacity: 1;
}

.conv__del:hover {
  color: var(--red);
  background: var(--red-soft);
}

.conv__del:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

/* 删除进行中：整条变淡，明确「正在处理」 */
.conv--removing {
  opacity: 0.5;
  pointer-events: none;
}

.conv:hover {
  background: var(--hover);
}

.conv--active {
  background: var(--paper);
  box-shadow: var(--shadow-xs);
}

.conv--active .conv__title {
  color: var(--ink);
  font-weight: 600;
}

.conv__title {
  font-size: 12.5px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv__meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--faint);
}

.conv__dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--faint);
  flex: none;
}

.sidebar__footer {
  margin-top: auto;
  padding: var(--s3) var(--s4);
  border-top: 1px solid var(--line);
}
</style>
