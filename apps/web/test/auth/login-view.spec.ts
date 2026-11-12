import { beforeEach, describe, expect, it } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { http, HttpResponse } from 'msw';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter, type Router } from 'vue-router';
import LoginView from '@/features/auth/views/LoginView.vue';
import { TOKEN_KEY, getToken } from '@/api';
import { server } from '@/mocks/node';
import { resetState } from '@/mocks/state';

/**
 * 登录页（P6 / features/auth）。
 *
 * 真走 MSW 的 `POST /api/v1/auth/login`：验证 token 真的落到 localStorage、
 * 真的按 redirect 跳转，而不是只断言「按钮点得动」。
 *
 * 注意：MSW 的 fetch 走宏任务链，`flushPromises()` 只排空微任务，
 * 所以凡是「等接口回来」的断言一律用下面的 waitFor 轮询，不要用固定 sleep。
 */

let pinia: ReturnType<typeof createPinia>;

async function waitFor(check: () => boolean, timeout = 4000, label = ''): Promise<void> {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    await flushPromises();
    if (check()) return;
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw new Error(`等待超时${label ? `：${label}` : ''}`);
}

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', name: 'login', component: { template: '<div />' } },
      { path: '/chat', name: 'chat', component: { template: '<div />' } },
      { path: '/knowledge', name: 'knowledge', component: { template: '<div />' } },
    ],
  });
}

async function mountPage(query: Record<string, string> = {}) {
  const router = makeRouter();
  await router.push({ name: 'login', query });
  await router.isReady();
  const wrapper = mount(LoginView, {
    global: { plugins: [ElementPlus, router, pinia] },
    attachTo: document.body,
  });
  await flushPromises();
  return { wrapper, router };
}

describe('登录页（P6）', () => {
  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    resetState();
    window.localStorage.clear();
    document.documentElement.dataset.theme = 'light';
  });

  it('渲染真实账号说明与账密表单', async () => {
    const { wrapper } = await mountPage();

    expect(wrapper.find('[data-testid="page-login"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="login-auth-note"]').text()).toContain('账号登录');
    expect(wrapper.find('[data-testid="login-demo"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="login-form"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="login-submit"]').attributes('disabled')).toBeDefined();
  });

  it('登录后按 redirect 回到原来想去的页面', async () => {
    const { wrapper, router } = await mountPage({ redirect: '/knowledge' });

    await wrapper.get('[data-testid="login-username"]').setValue('alice');
    await wrapper.get('[data-testid="login-password"]').setValue('pass-alice-123');
    await wrapper.get('[data-testid="login-submit"]').trigger('click');

    await waitFor(() => router.currentRoute.value.fullPath === '/knowledge', 4000, '回到 /knowledge');
    expect(getToken()).toBeTruthy();
    expect(window.localStorage.getItem(TOKEN_KEY)).toBeTruthy();
  });

  it('redirect 是站外地址时回落对话页', async () => {
    const { wrapper, router } = await mountPage({ redirect: '//evil.com/steal' });

    await wrapper.get('[data-testid="login-username"]').setValue('alice');
    await wrapper.get('[data-testid="login-password"]').setValue('pass-alice-123');
    await wrapper.get('[data-testid="login-submit"]').trigger('click');

    await waitFor(() => router.currentRoute.value.fullPath === '/chat', 4000, '回落到 /chat');
  });

  it('账密表单：填全才可提交，提交成功后同样落 token', async () => {
    const { wrapper, router } = await mountPage();

    await wrapper.get('[data-testid="login-username"]').setValue('demo');
    await wrapper.get('[data-testid="login-password"]').setValue('demo');
    await flushPromises();
    expect(wrapper.get('[data-testid="login-submit"]').attributes('disabled')).toBeUndefined();

    await wrapper.get('[data-testid="login-submit"]').trigger('click');

    await waitFor(() => router.currentRoute.value.name === 'chat', 4000, '账密登录后跳转');
    expect(getToken()).toBeTruthy();
  });

  it('只有空白用户名时前端先挡住，不发请求也不写 token', async () => {
    const { wrapper, router } = await mountPage();

    await wrapper.get('[data-testid="login-username"]').setValue('   ');
    await wrapper.get('[data-testid="login-password"]').setValue('x');
    await flushPromises();

    expect(wrapper.get('[data-testid="login-submit"]').attributes('disabled')).toBeDefined();
    // 强行点一次，仍然不应该有任何请求发出
    await wrapper.get('[data-testid="login-submit"]').trigger('click');
    await flushPromises();

    expect(getToken()).toBeNull();
    expect(router.currentRoute.value.name).toBe('login');
  });

  it('后端返回业务错误时展示错误文案、停在登录页', async () => {
    server.use(
      http.post('*/api/v1/auth/login', () =>
        HttpResponse.json({ code: 40001, message: '用户名或密码错误', data: null }),
      ),
    );
    const { wrapper, router } = await mountPage();

    await wrapper.get('[data-testid="login-username"]').setValue('demo');
    await wrapper.get('[data-testid="login-password"]').setValue('wrong');
    await wrapper.get('[data-testid="login-submit"]').trigger('click');

    await waitFor(
      () => wrapper.find('[data-testid="login-error"]').exists(),
      4000,
      '错误提示出现',
    );
    expect(wrapper.get('[data-testid="login-error"]').text()).toContain('用户名或密码错误');
    expect(getToken()).toBeNull();
    expect(router.currentRoute.value.name).toBe('login');
  });

  it('主题切换按钮真的翻转 <html data-theme>', async () => {
    const { wrapper } = await mountPage();
    const root = document.documentElement;

    const before = root.dataset.theme;
    await wrapper.get('[data-testid="login-theme"]').trigger('click');
    await flushPromises();
    const after = root.dataset.theme;

    expect(after).not.toBe(before);
    expect(['light', 'dark']).toContain(after);
    expect(window.localStorage.getItem('xiaoyi.theme')).toBe(after);
  });
});
