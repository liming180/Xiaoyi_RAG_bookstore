import { beforeEach, describe, expect, it } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import ElementPlus, { ElMessageBox } from 'element-plus';
import { vi } from 'vitest';
import AdminUserListView from '@/features/admin/views/AdminUserListView.vue';
import { resetMockUsers } from '@/mocks/handlers';
import { setRole } from '@/app/router/role';

/**
 * 管理端用户管理页（06 号设计方案 §9.3）。
 *
 * 走真实 MSW handler（不是手写 stub）：这样「列表只回未软删」「admin 行只读」
 * 「重名 40905」这些**后端语义**也一起被验证，而不是只验证组件渲染。
 */
function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', redirect: '/admin/users' },
      { path: '/admin/users', name: 'admin-users', component: { template: '<div />' } },
      { path: '/chat', name: 'chat', component: { template: '<div />' } },
      { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
    ],
  });
}

async function mountPage() {
  const router = makeRouter();
  const wrapper = mount(AdminUserListView, {
    global: {
      plugins: [ElementPlus, router],
    },
  });
  await flushPromises();
  // 列表首次加载是 onMounted 里的异步请求，等它落定
  await flushPromises();
  return wrapper;
}

describe('管理端用户管理页', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetMockUsers();
    setRole('ADMIN');
  });

  it('挂载后拉列表：软删行不出现，总数只算未删的', async () => {
    const wrapper = await mountPage();

    expect(wrapper.find('[data-testid="admin-user-total"]').text()).toContain('3');
    const text = wrapper.text();
    expect(text).toContain('admin');
    expect(text).toContain('u01');
    // u03 是软删种子行，默认列表里不该出现
    expect(text).not.toContain('u03');
  });

  it('admin 行是只读的：只显示「当前管理员」，没有操作按钮', async () => {
    const wrapper = await mountPage();

    const firstRow = wrapper.find('[data-testid="admin-user-table"] tbody tr');
    expect(firstRow.text()).toContain('当前管理员');
    expect(firstRow.find('[data-testid="admin-user-edit"]').exists()).toBe(false);
    expect(firstRow.find('[data-testid="admin-user-delete"]').exists()).toBe(false);
  });

  it('普通用户行有三个操作按钮', async () => {
    const wrapper = await mountPage();

    const rows = wrapper.findAll('[data-testid="admin-user-table"] tbody tr');
    const userRow = rows[1];
    expect(userRow.find('[data-testid="admin-user-edit"]').exists()).toBe(true);
    expect(userRow.find('[data-testid="admin-user-reset-password"]').exists()).toBe(true);
    expect(userRow.find('[data-testid="admin-user-delete"]').exists()).toBe(true);
  });

  it('搜索按关键字过滤，重置回到全量', async () => {
    const wrapper = await mountPage();

    const search = wrapper.findComponent({ name: 'ElInput' });
    search.vm.$emit('update:modelValue', '张三');
    await wrapper.find('[data-testid="admin-user-search-submit"]').trigger('click');
    await flushPromises();

    expect(wrapper.find('[data-testid="admin-user-total"]').text()).toContain('1');
    expect(wrapper.text()).toContain('u01');

    await wrapper.find('[data-testid="admin-user-reset"]').trigger('click');
    await flushPromises();
    expect(wrapper.find('[data-testid="admin-user-total"]').text()).toContain('3');
  });

  it('点击新建按钮会打开弹窗组件（编辑态为 null）', async () => {
    const wrapper = await mountPage();

    await wrapper.find('[data-testid="admin-user-create"]').trigger('click');
    await flushPromises();

    const dialog = wrapper.findComponent({ name: 'AdminUserFormDialog' });
    expect(dialog.exists()).toBe(true);
    expect(dialog.props('modelValue')).toBe(true);
    expect(dialog.props('target')).toBeNull();
  });

  it('点击编辑把该行传进弹窗（编辑态 username 只读）', async () => {
    const wrapper = await mountPage();

    const rows = wrapper.findAll('[data-testid="admin-user-table"] tbody tr');
    await rows[1].find('[data-testid="admin-user-edit"]').trigger('click');
    await flushPromises();

    const dialog = wrapper.findComponent({ name: 'AdminUserFormDialog' });
    expect(dialog.props('modelValue')).toBe(true);
    expect(dialog.props('target')).toMatchObject({ username: 'u01', role: 'USER' });
  });

  it('删除需二次确认，确认后列表少一行', async () => {
    const wrapper = await mountPage();
    const confirmSpy = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never);

    const rows = wrapper.findAll('[data-testid="admin-user-table"] tbody tr');
    await rows[1].find('[data-testid="admin-user-delete"]').trigger('click');
    await flushPromises();
    await flushPromises();

    expect(confirmSpy).toHaveBeenCalled();
    expect(confirmSpy.mock.calls[0][0]).toContain('立即无法登录');
    expect(wrapper.find('[data-testid="admin-user-total"]').text()).toContain('2');

    confirmSpy.mockRestore();
  });

  it('取消删除时不发请求，列表不变', async () => {
    const wrapper = await mountPage();
    const confirmSpy = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockRejectedValue(new Error('cancel') as never);

    const rows = wrapper.findAll('[data-testid="admin-user-table"] tbody tr');
    await rows[1].find('[data-testid="admin-user-delete"]').trigger('click');
    await flushPromises();

    expect(wrapper.find('[data-testid="admin-user-total"]').text()).toContain('3');

    confirmSpy.mockRestore();
  });

  it('列表为空时显示空态文案', async () => {
    const wrapper = await mountPage();

    const search = wrapper.findComponent({ name: 'ElInput' });
    search.vm.$emit('update:modelValue', '不存在的名字');
    await wrapper.find('[data-testid="admin-user-search-submit"]').trigger('click');
    await flushPromises();

    expect(wrapper.text()).toContain('没有匹配的用户');
    expect(wrapper.find('[data-testid="admin-user-total"]').text()).toContain('0');
  });
});
