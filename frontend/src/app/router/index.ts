import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';
import { getToken } from '@/api';
import { resolveNavigation } from './guard';

/**
 * 路由表（规格 §4）。
 *
 * 全部懒加载：首屏只加载 AppShell + 当前页，避免把知识库/评测页的代码塞进初始 bundle。
 * 顺序无关，但 /chat/:id? 必须放在 /chat 之后，避免空 id 被当成参数。
 */
const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/chat' },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/features/auth/views/LoginView.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/chat/:id?',
    name: 'chat',
    component: () => import('@/features/chat/views/ChatView.vue'),
    meta: { title: '对话' },
  },
  {
    path: '/knowledge',
    name: 'knowledge',
    component: () => import('@/features/knowledge/views/KnowledgeView.vue'),
    meta: { title: '知识库' },
  },
  {
    path: '/knowledge/chunks',
    name: 'chunks',
    component: () => import('@/features/knowledge/views/ChunksView.vue'),
    meta: { title: '片段浏览' },
  },
  {
    path: '/eval',
    name: 'eval',
    component: () => import('@/features/eval/views/EvalView.vue'),
    meta: { title: '评测' },
  },
  { path: '/:pathMatch(.*)*', redirect: '/chat' },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
});

router.beforeEach((to) => {
  // 每次导航现读 token，而不是缓存一个 boolean：
  // 401 拦截器清 token 后不需要额外通知路由，下一次跳转自然会被拦回登录页。
  const decision = resolveNavigation(to, Boolean(getToken()));
  return decision;
});

router.afterEach((to) => {
  const title = to.meta.title as string | undefined;
  document.title = title ? `${title} · 小忆 RAG 知识库问答` : '小忆 RAG 知识库问答';
});

export default router;
