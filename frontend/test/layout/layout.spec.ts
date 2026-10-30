import { describe, expect, it, beforeEach } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import ElementPlus from 'element-plus';
import StatusLight from '@/app/layout/StatusLight.vue';
import StatusBanner from '@/app/layout/StatusBanner.vue';
import AppSidebar from '@/app/layout/AppSidebar.vue';
import { useSystemStatusStore } from '@/stores/systemStatus';
import { resetState } from '@/mocks/state';

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', redirect: '/chat' },
      { path: '/chat', name: 'chat', component: { template: '<div />' } },
      { path: '/knowledge', name: 'knowledge', component: { template: '<div />' } },
      { path: '/eval', name: 'eval', component: { template: '<div />' } },
      // 兜底：内存路由初始路径是 ''，没有 catch-all 会打印 "No match found for location"
      { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
    ],
  });
}

function mountWithPinia<T>(component: T, options: Record<string, unknown> = {}) {
  // 组件里用了 useRouter()，必须注入真实 router，否则会打印 injection "Symbol(router)" not found
  const router = makeRouter();
  return mount(component as never, {
    global: {
      plugins: [ElementPlus, router],
      stubs: { 'el-tooltip': { template: '<span><slot /></span>' } },
      ...(options.global as object),
    },
    ...options,
  });
}

describe('StatusLight（F03 状态灯）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('ready 时绿灯 + 已就绪文案', async () => {
    const store = useSystemStatusStore();
    store.markReady(15);
    store.detail = {
      status: 'ready',
      docCount: 6,
      chunkCount: 15,
      chunkSize: 180,
      overlap: 30,
      embeddingModel: 'mock',
      lastBuiltAt: 1,
      reason: null,
    };
    const wrapper = mountWithPinia(StatusLight);
    expect(wrapper.get('[data-testid="status-light"]').classes()).toContain('status-light--ok');
    expect(wrapper.text()).toContain('知识库已就绪');
  });

  it('needs_rebuild 时黄灯 + 资料待更新', () => {
    const store = useSystemStatusStore();
    store.markNeedsRebuild('资料已变更');
    const wrapper = mountWithPinia(StatusLight);
    expect(wrapper.get('[data-testid="status-light"]').classes()).toContain('status-light--warn');
    expect(wrapper.text()).toContain('资料待更新');
  });

  it('unavailable 时红灯 + 暂不可用', () => {
    const store = useSystemStatusStore();
    store.status = 'unavailable';
    const wrapper = mountWithPinia(StatusLight);
    expect(wrapper.get('[data-testid="status-light"]').classes()).toContain('status-light--error');
    expect(wrapper.text()).toContain('知识库暂不可用');
  });
});

describe('StatusBanner（F03 横幅）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('ready 且未降级时不渲染', () => {
    const store = useSystemStatusStore();
    store.markReady(15);
    const wrapper = mountWithPinia(StatusBanner);
    expect(wrapper.find('[data-testid="status-banner"]').exists()).toBe(false);
  });

  it('needs_rebuild 显示琥珀横幅 + 重新建库按钮', () => {
    const store = useSystemStatusStore();
    store.markNeedsRebuild('资料已变更');
    const wrapper = mountWithPinia(StatusBanner);
    const banner = wrapper.get('[data-testid="status-banner"]');
    expect(banner.classes()).toContain('status-banner--warn');
    expect(banner.text()).toContain('重新建库后即可使用最新资料提问');
    expect(wrapper.find('[data-testid="banner-rebuild"]').exists()).toBe(true);
  });

  it('unavailable 显示红色横幅 + 重试', () => {
    const store = useSystemStatusStore();
    store.status = 'unavailable';
    const wrapper = mountWithPinia(StatusBanner);
    const banner = wrapper.get('[data-testid="status-banner"]');
    expect(banner.classes()).toContain('status-banner--error');
    expect(banner.text()).toContain('仅「直接答」模式可用');
  });

  it('SSE 降级时也显示横幅', () => {
    const store = useSystemStatusStore();
    store.markReady(15);
    store.setDegraded(true);
    const wrapper = mountWithPinia(StatusBanner);
    expect(wrapper.get('[data-testid="status-banner"]').text()).toContain('AI 服务暂时降级');
  });
});

describe('AppSidebar（导航）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('渲染三个导航项且当前项高亮', async () => {
    // 组合式 API 里 useRoute/useRouter 读的是真实 router 注入，所以这里用内存路由
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/chat', name: 'chat', component: { template: '<div />' } },
        { path: '/knowledge', name: 'knowledge', component: { template: '<div />' } },
        { path: '/eval', name: 'eval', component: { template: '<div />' } },
      ],
    });
    await router.push('/chat');
    await router.isReady();

    const wrapper = mount(AppSidebar, {
      global: { plugins: [ElementPlus, router] },
    });

    const items = wrapper.findAll('.sidebar__item');
    expect(items).toHaveLength(3);
    expect(items.map((i) => i.text())).toEqual(['对话', '知识库', '评测']);
    expect(items[0]?.classes()).toContain('sidebar__item--active');
    expect(items[0]?.attributes('aria-current')).toBe('page');

    // 点击第二项应导航到 /knowledge
    await items[1]!.trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.name).toBe('knowledge');
  });
});
