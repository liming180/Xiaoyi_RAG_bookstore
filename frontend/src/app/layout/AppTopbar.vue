<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { ChatDotRound, DataLine, Moon, Sunny, SwitchButton, TrendCharts } from '@element-plus/icons-vue';
import { APP_TITLE } from '@/constants/app';
import { authApi } from '@/api';
import { useConversationsStore } from '@/stores/conversations';
import { useUiPrefsStore } from '@/stores/uiPrefs';
import StatusLight from './StatusLight.vue';

/**
 * 顶栏：产品名 + 会话切换 + 状态灯 + 主题切换 + 配置入口。
 */
const router = useRouter();
const conversations = useConversationsStore();
const uiPrefs = useUiPrefsStore();

const activeId = computed({
  get: () => conversations.activeId,
  set: (id: string | null) => {
    if (!id) return;
    conversations.setActive(id);
    if (router.currentRoute.value.name !== 'chat') {
      void router.push({ name: 'chat' });
    }
  },
});

async function onCreate(): Promise<void> {
  const conv = await conversations.create();
  if (conv && router.currentRoute.value.name !== 'chat') {
    void router.push({ name: 'chat' });
  }
}

function goSettings(): void {
  void router.push({ name: 'knowledge', query: { panel: 'settings' } });
}

function onLogout(): void {
  authApi.logout();
  void router.push({ name: 'login' });
}
</script>

<template>
  <header class="topbar" data-testid="app-topbar">
    <div class="topbar__brand">
      <el-icon class="topbar__logo"><ChatDotRound /></el-icon>
      <span class="topbar__title">{{ APP_TITLE }}</span>
    </div>

    <div class="topbar__center">
      <el-select
        v-model="activeId"
        class="topbar__conv"
        size="small"
        placeholder="选择会话"
        data-testid="conversation-switcher"
      >
        <el-option
          v-for="conv in conversations.list"
          :key="conv.id"
          :label="conv.title || conv.id"
          :value="conv.id"
        />
      </el-select>
      <el-button size="small" text data-testid="conversation-create" @click="onCreate">
        + 新会话
      </el-button>
    </div>

    <div class="topbar__right">
      <StatusLight />
      <el-tooltip :content="uiPrefs.theme === 'dark' ? '切换到浅色' : '切换到深色'" placement="bottom">
        <el-button
          size="small"
          text
          :icon="uiPrefs.theme === 'dark' ? Sunny : Moon"
          data-testid="theme-toggle"
          aria-label="切换主题"
          @click="uiPrefs.toggle()"
        />
      </el-tooltip>
      <el-button
        size="small"
        text
        :icon="TrendCharts"
        data-testid="nav-eval"
        @click="router.push({ name: 'eval' })"
      >
        评测
      </el-button>
      <el-button
        size="small"
        text
        :icon="DataLine"
        data-testid="nav-knowledge"
        @click="router.push({ name: 'knowledge' })"
      >
        知识库
      </el-button>
      <el-button size="small" text data-testid="nav-settings" @click="goSettings">配置</el-button>
      <el-button
        size="small"
        text
        :icon="SwitchButton"
        data-testid="nav-logout"
        aria-label="退出登录"
        @click="onLogout"
      />
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: 16px;
  height: var(--header-h);
  padding: 0 16px;
  background: var(--paper);
  border-bottom: 1px solid var(--line);
  flex: 0 0 auto;
}

.topbar__brand {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.topbar__logo {
  color: var(--teal);
  font-size: 18px;
}

.topbar__title {
  font-weight: 600;
  color: var(--ink);
  white-space: nowrap;
}

.topbar__center {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.topbar__conv {
  width: 220px;
}

.topbar__right {
  display: flex;
  align-items: center;
  gap: 4px;
}

@media (max-width: 900px) {
  .topbar__title {
    display: none;
  }

  .topbar__conv {
    width: 140px;
  }
}
</style>
