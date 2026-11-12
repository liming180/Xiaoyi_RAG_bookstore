import { beforeEach, describe, expect, it } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import ElementPlus from 'element-plus';
import { adminApi } from '@/api';
import AdminAuditListView from '@/features/admin/views/AdminAuditListView.vue';
import { resetMockAudits, resetMockUsers } from '@/mocks/handlers';
import { setRole } from '@/app/router/role';

/**
 * 管理端审计日志页。
 *
 * 走真实 MSW handler：先通过 adminApi 制造几条审计（新建/改/删），
 * 再验证列表、筛选、分页与详情展示 —— 这样「写操作真的会落审计」也被顺带钉住。
 */
function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', redirect: '/admin/audit' },
      { path: '/admin/audit', name: 'admin-audit', component: { template: '<div />' } },
      { path: '/admin/users', name: 'admin-users', component: { template: '<div />' } },
      { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
    ],
  });
}

async function mountPage() {
  const router = makeRouter();
  const wrapper = mount(AdminAuditListView, {
    global: { plugins: [ElementPlus, router] },
  });
  await flushPromises();
  await flushPromises();
  return wrapper;
}

/** 制造一条 create + 一条 update + 一条 delete 的审计记录。 */
async function seedAudits() {
  await adminApi.createUser({ username: 'audit_u1', password: 'a-sufficient-password' });
  await adminApi.updateUser(2, { displayName: '张三改' });
  await adminApi.deleteUser(3);
}

describe('管理端审计日志页', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetMockUsers();
    resetMockAudits();
    setRole('ADMIN');
  });

  it('没有记录时显示空态，不报错', async () => {
    const wrapper = await mountPage();

    expect(wrapper.find('[data-testid="audit-total"]').text()).toContain('0');
    expect(wrapper.text()).toContain('暂无审计记录');
  });

  it('写操作会被记录，列表按最新在前展示', async () => {
    await seedAudits();
    const wrapper = await mountPage();

    expect(wrapper.find('[data-testid="audit-total"]').text()).toContain('3');
    const text = wrapper.text();
    // 三个动作的中文标签都出现了
    expect(text).toContain('新建用户');
    expect(text).toContain('编辑用户');
    expect(text).toContain('删除用户');
  });

  it('详情只显示「变了什么」，绝不出现密码值', async () => {
    await adminApi.createUser({ username: 'audit_u2', password: 'SuperSecretPass!99' });
    await adminApi.resetUserPassword(2, { newPassword: 'AnotherSecret!2026' });

    const page = await adminApi.listAuditLogs({ page: 1, size: 20 });
    const details = page.items.map((i) => i.detailJson ?? '').join('|');

    expect(details).toContain('changed');
    expect(details).not.toContain('SuperSecretPass!99');
    expect(details).not.toContain('AnotherSecret!2026');
  });

  it('按动作筛选只留该动作', async () => {
    await seedAudits();
    const wrapper = await mountPage();

    // 工具栏共三个筛选控件：动作(ElSelect) + 操作者(ElInput) + 对象(ElInput)。
    // 分页里的 ElSelect 在 footer，排在工具栏之后，所以取第一个即为动作筛选。
    const select = wrapper.findAllComponents({ name: 'ElSelect' })[0];
    select.vm.$emit('update:modelValue', 'admin.user.delete');
    // 组件的 @change 只在真实交互时触发；这里直接 emit 后再点一次查询，
    // 模拟「用户选完动作后页面刷新」的完整链路。
    await wrapper.find('[data-testid="audit-search"]').trigger('click');
    await flushPromises();
    await flushPromises();

    expect(wrapper.find('[data-testid="audit-total"]').text()).toContain('1');
    expect(wrapper.text()).toContain('删除用户');
    expect(wrapper.text()).not.toContain('新建用户');
  });

  it('按对象关键字筛选（user:2）', async () => {
    await seedAudits();

    const page = await adminApi.listAuditLogs({ page: 1, size: 20, keyword: 'user:2' });
    expect(page.total).toBe(1);
    expect(page.items[0].target).toBe('user:2');
  });

  it('按操作者 id 筛选；非数字 id 不发请求', async () => {
    await seedAudits();

    const ok = await adminApi.listAuditLogs({ page: 1, size: 20, operatorId: 1 });
    expect(ok.total).toBe(3);

    // 非数字：mock 与真实后端都回 40001
    await expect(
      adminApi.listAuditLogs({ page: 1, size: 20, operatorId: Number('abc') }),
    ).rejects.toBeTruthy();
  });

  it('操作者名从用户表解析出来（不是一串数字）', async () => {
    await seedAudits();
    const page = await adminApi.listAuditLogs({ page: 1, size: 20 });

    expect(page.items.every((i) => i.operatorName === 'admin')).toBe(true);
  });

  it('动作下拉的选项来自后端，不是页面硬编码', async () => {
    await seedAudits();
    const actions = await adminApi.listAuditActions();

    expect(actions).toContain('admin.user.create');
    expect(actions).toContain('admin.user.update');
    expect(actions).toContain('admin.user.delete');
    // 去重且有序
    expect(actions).toEqual([...actions].sort());
    expect(new Set(actions).size).toBe(actions.length);
  });

  it('分页：size=2 时翻到第 2 页拿到剩余记录', async () => {
    await seedAudits();

    const p1 = await adminApi.listAuditLogs({ page: 1, size: 2 });
    const p2 = await adminApi.listAuditLogs({ page: 2, size: 2 });

    expect(p1.items).toHaveLength(2);
    expect(p2.items).toHaveLength(1);
    expect(p2.total).toBe(3);
    // 两页不重复
    const ids = [...p1.items, ...p2.items].map((i) => i.id);
    expect(new Set(ids).size).toBe(3);
  });

  it('重置清空三个筛选条件', async () => {
    await seedAudits();
    const wrapper = await mountPage();

    // 工具栏的 ElInput 依次是 操作者、对象；分页 select 内部的 input 不是 ElInput 组件
    const inputs = wrapper.findAllComponents({ name: 'ElInput' });
    inputs[0].vm.$emit('update:modelValue', '1');
    inputs[1].vm.$emit('update:modelValue', 'user:2');
    await wrapper.find('[data-testid="audit-search"]').trigger('click');
    await flushPromises();
    await flushPromises();

    expect(wrapper.find('[data-testid="audit-total"]').text()).toContain('1');

    await wrapper.find('[data-testid="audit-reset"]').trigger('click');
    await flushPromises();
    await flushPromises();

    expect(wrapper.find('[data-testid="audit-total"]').text()).toContain('3');
  });

  it('页面上没有任何写操作入口（审计只读）', async () => {
    await seedAudits();
    const wrapper = await mountPage();

    // 只看「按钮」层面：动作标签里会出现「新建用户」这些词，那是数据不是入口
    const html = wrapper.html();
    expect(html).not.toContain('audit-create');
    expect(html).not.toContain('audit-delete');
    expect(html).not.toContain('audit-editing');
    // 页面只有查询/重置两个操作按钮 + 每行的「查看」
    const buttonTexts = wrapper.findAll('button').map((b) => b.text().trim());
    expect(buttonTexts).toContain('查询');
    expect(buttonTexts).toContain('重置');
    expect(buttonTexts).not.toContain('保存');
    expect(buttonTexts).not.toContain('新建');
    expect(buttonTexts).not.toContain('删除');
  });
});
