<script setup lang="ts">
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { SwitchButton, UserFilled } from '@element-plus/icons-vue';
import { authApi } from '@/api';
import { APP_TITLE } from '@/constants/app';
import { useUiPrefsStore } from '@/stores/uiPrefs';

/**
 * 管理端外壳。
 *
 * 与用户端 AppShell 的差别是刻意的：管理端只有管理类页面，不需要会话切换、不需要状态灯 ——
 * 只留「这是管理端」「有哪几页」「怎么退出」三件事。组件仍全部来自 Element Plus，
 * 不引入新的 UI 依赖（06 号方案 §4.5 的约束）。
 *
 * 导航用顶栏下的标签页而不是侧栏：管理端页面数量少（用户管理 + 审计日志），
 * 侧栏在这里是多余的一层结构。标签页也天然回答了「我在哪一页」。
 */
const route = useRoute();
const router = useRouter();
const uiPrefs = useUiPrefsStore();

const tabs = [
  { name: 'admin-users', label: '用户管理', testid: 'admin-tab-users' },
  { name: 'admin-audit', label: '审计日志', testid: 'admin-tab-audit' },
] as const;

const current = computed(() => (route.name as string) ?? 'admin-users');

function go(name: string): void {
  if (route.name !== name) void router.push({ name });
}

function onLogout(): void {
  authApi.logout();
  void router.push({ name: 'login' });
}
</script>

<template>
  <div class="admin-shell" data-testid="admin-shell">
    <header class="admin-topbar">
      <div class="admin-topbar__brand">
        <span class="admin-topbar__logo"><el-icon><UserFilled /></el-icon></span>
        <span class="admin-topbar__title">管理端 · {{ APP_TITLE }}</span>
      </div>

      <div class="admin-topbar__right">
        <el-tooltip :content="uiPrefs.theme === 'dark' ? '切换到浅色' : '切换到深色'" placement="bottom">
          <el-button
            size="small"
            text
            data-testid="admin-theme-toggle"
            @click="uiPrefs.toggle()"
          >
            {{ uiPrefs.theme === 'dark' ? '☀ 浅色' : '🌙 深色' }}
          </el-button>
        </el-tooltip>
        <el-button
          size="small"
          text
          :icon="SwitchButton"
          data-testid="admin-logout"
          aria-label="退出登录"
          @click="onLogout"
        >
          退出登录
        </el-button>
      </div>
    </header>

    <div class="admin-tabs" data-testid="admin-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.name"
        type="button"
        class="admin-tabs__item"
        :class="{ 'admin-tabs__item--active': current === tab.name }"
        :data-testid="tab.testid"
        :aria-current="current === tab.name ? 'page' : undefined"
        @click="go(tab.name)"
      >
        {{ tab.label }}
      </button>
    </div>

    <main class="admin-main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.admin-shell {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--bg);
}

.admin-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s4);
  height: 56px;
  padding: 0 var(--s5);
  background: var(--paper);
  border-bottom: 1px solid var(--line);
}

.admin-topbar__brand {
  display: flex;
  align-items: center;
  gap: 8px;
}

.admin-topbar__logo {
  display: inline-flex;
  color: var(--teal);
  font-size: 18px;
}

.admin-topbar__title {
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
}

.admin-topbar__right {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.admin-tabs {
  display: flex;
  align-items: center;
  gap: var(--s1);
  padding: 0 var(--s5);
  background: var(--paper);
  border-bottom: 1px solid var(--line);
}

.admin-tabs__item {
  position: relative;
  padding: 10px 14px;
  font-size: 13px;
  color: var(--muted);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
}

.admin-tabs__item:hover {
  color: var(--ink);
}

.admin-tabs__item--active {
  color: var(--teal-dark);
  font-weight: 600;
  border-bottom-color: var(--teal);
}

.admin-main {
  flex: 1;
  padding: var(--s4) var(--s5) var(--s6);
}
</style>
