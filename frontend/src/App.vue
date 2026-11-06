<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import AppShell from '@/app/layout/AppShell.vue';

/**
 * 根组件只做一件事：决定当前路由要不要套应用外壳。
 *
 * 登录页是 public 页，必须独占整屏 —— 套上顶栏和左导航会出现「未登录却能点导航」
 * 的怪状态，也会让登录页的账号入口被顶栏抢走视觉重心。
 */
const route = useRoute();
const bare = computed(() => route.meta.public === true);
</script>

<template>
  <router-view v-if="bare" />
  <AppShell v-else />
</template>
