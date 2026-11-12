<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import AppSidebar from './AppSidebar.vue';
import AppTopbar from './AppTopbar.vue';
import StatusBanner from './StatusBanner.vue';
import ExperimentBanner from './ExperimentBanner.vue';
import { useSystemStatusStore } from '@/stores/systemStatus';
import { useConversationsStore } from '@/stores/conversations';
import { useUiPrefsStore } from '@/stores/uiPrefs';
import { on } from '@/api';

/**
 * 应用外壳。
 *
 * 布局：顶栏（56px）+ 状态横幅 + [左导航 | 内容区]。
 * 响应式：<1080px 时左导航收进抽屉（与旧版 U01 的唯一断点保持一致）。
 */
const router = useRouter();
const systemStatus = useSystemStatusStore();
const conversations = useConversationsStore();
const uiPrefs = useUiPrefsStore();

const drawerOpen = ref(false);
const narrow = ref(false);

let media: MediaQueryList | null = null;

function onMediaChange(e: MediaQueryListEvent | MediaQueryList): void {
  narrow.value = e.matches;
  if (!e.matches) drawerOpen.value = false;
}

const offDegraded = on('system:degraded', () => systemStatus.setDegraded(true));
const offRestored = on('system:restored', () => systemStatus.setDegraded(false));
const offExperiment = on('experiment:running', (running) => systemStatus.setExperimentRunning(running));
const offAuth = on('auth:expired', () => {
  void router.push({ name: 'login' });
});

onMounted(() => {
  uiPrefs.init();
  systemStatus.startPolling();
  void conversations.fetchList();

  media = window.matchMedia('(max-width: 1080px)');
  onMediaChange(media);
  media.addEventListener('change', onMediaChange);
});

onBeforeUnmount(() => {
  systemStatus.stopPolling();
  offDegraded();
  offRestored();
  offExperiment();
  offAuth();
  media?.removeEventListener('change', onMediaChange);
});
</script>

<template>
  <div class="shell" data-testid="app-shell">
    <AppTopbar />

    <StatusBanner />
    <ExperimentBanner />

    <div class="shell__body">
      <AppSidebar v-if="!narrow" />

      <el-drawer
        v-else
        v-model="drawerOpen"
        direction="ltr"
        size="240px"
        :with-header="false"
        data-testid="nav-drawer"
      >
        <AppSidebar @click="drawerOpen = false" />
      </el-drawer>

      <main class="shell__main" role="main">
        <router-view />
      </main>
    </div>

    <el-button
      v-if="narrow"
      class="shell__fab"
      circle
      type="primary"
      data-testid="nav-toggle"
      aria-label="打开导航"
      @click="drawerOpen = true"
    >
      ☰
    </el-button>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: var(--bg);
}

.shell__body {
  display: flex;
  flex: 1;
  min-height: 0;
}

/*
 * A-2 修复（2026-11-09）：原来是 display:block。
 * 子页（如 .chat-view）用 flex:1 想撑满高度，但 block 父级里 flex 属性完全失效 ——
 * 实测视口 699px 时聊天内容只占 528px，输入框下方空出 171px。
 * 改成 flex column 后子页的 flex:1 才真正生效。
 */
.shell__main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: auto;
}

.shell__fab {
  position: fixed;
  left: 16px;
  bottom: 16px;
  z-index: 20;
}
</style>
