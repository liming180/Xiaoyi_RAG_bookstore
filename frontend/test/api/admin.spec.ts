import { beforeEach, describe, expect, it } from 'vitest';
import { adminApi, ApiError, authApi } from '@/api';
import { resetMockUsers } from '@/mocks/handlers';
import { setRole } from '@/app/router/role';

/**
 * 管理端 API 与 mock 层（06 号设计方案 §9.3）。
 *
 * mock 层模拟了真实后端的四条不变量，所以这些用例同时验证两件事：
 * 前端封装的请求形状对，以及「造不出第二个管理员 / 管理员行不可操作 / 软删即不显示」
 * 这套语义在联调期就能被门禁发现。
 */
describe('管理端用户管理 API（走 MSW）', () => {
  beforeEach(() => {
    resetMockUsers();
    setRole('ADMIN');
  });

  it('分页列表默认只回未软删的行，且 admin 在首位', async () => {
    const page = await adminApi.listUsers({ page: 1, size: 20 });

    expect(page.total).toBe(3); // 种子里 u03 是软删行
    expect(page.page).toBe(1);
    expect(page.items[0].username).toBe('admin');
    expect(page.items.every((u) => !u.deleted)).toBe(true);
  });

  it('includeDeleted 才把软删行带出来', async () => {
    const page = await adminApi.listUsers({ page: 1, size: 20, includeDeleted: true });

    expect(page.total).toBe(4);
    expect(page.items.some((u) => u.deleted)).toBe(true);
  });

  it('keyword 同时匹配用户名前缀与显示名包含', async () => {
    const byName = await adminApi.listUsers({ page: 1, size: 20, keyword: 'u0' });
    expect(byName.total).toBe(2); // u01 + u02（u03 已软删）

    const byDisplay = await adminApi.listUsers({ page: 1, size: 20, keyword: '张三' });
    expect(byDisplay.total).toBe(1);
    expect(byDisplay.items[0].username).toBe('u01');
  });

  it('新建用户返回 USER 角色（接口造不出第二个管理员）', async () => {
    const created = await adminApi.createUser({
      username: 'u09',
      password: 'a-sufficient-password',
      displayName: '新同学',
    });

    expect(created.role).toBe('USER');
    expect(created.deleted).toBe(false);
    expect(created.displayName).toBe('新同学');
  });

  it('重名返回 40905，且软删行也占着这个名字', async () => {
    await expect(
      adminApi.createUser({ username: 'u01', password: 'a-sufficient-password' }),
    ).rejects.toMatchObject({ code: 40905, message: '用户名已存在' });

    // u03 是软删行，名字仍被占用
    await expect(
      adminApi.createUser({ username: 'u03', password: 'a-sufficient-password' }),
    ).rejects.toMatchObject({ code: 40905 });
  });

  it('密码按 UTF-8 字节判长度：25 个中文（75 字节）被拒', async () => {
    await expect(
      adminApi.createUser({ username: 'u10', password: '密'.repeat(25) }),
    ).rejects.toMatchObject({ code: 40001 });

    // 24 个中文正好 72 字节，可以通过
    const okUser = await adminApi.createUser({ username: 'u11', password: '密'.repeat(24) });
    expect(okUser.username).toBe('u11');
  });

  it('用户名形状不合规则被拒', async () => {
    await expect(
      adminApi.createUser({ username: '张三', password: 'a-sufficient-password' }),
    ).rejects.toMatchObject({ code: 40001 });
  });

  it('管理员行不能被编辑 / 重置密码 / 删除（40906）', async () => {
    await expect(adminApi.updateUser(1, { displayName: '篡改' })).rejects.toMatchObject({
      code: 40906,
    });
    await expect(
      adminApi.resetUserPassword(1, { newPassword: 'a-sufficient-password' }),
    ).rejects.toMatchObject({ code: 40906 });
    await expect(adminApi.deleteUser(1)).rejects.toMatchObject({ code: 40906 });
  });

  it('编辑普通用户只改显示名，用户名与角色不变', async () => {
    const updated = await adminApi.updateUser(2, { displayName: '张三丰' });

    expect(updated.username).toBe('u01');
    expect(updated.role).toBe('USER');
    expect(updated.displayName).toBe('张三丰');
  });

  it('删除是软删：列表里消失，includeDeleted 里还在', async () => {
    await adminApi.deleteUser(2);

    const visible = await adminApi.listUsers({ page: 1, size: 20 });
    expect(visible.items.some((u) => u.id === 2)).toBe(false);

    const all = await adminApi.listUsers({ page: 1, size: 20, includeDeleted: true });
    expect(all.items.find((u) => u.id === 2)?.deleted).toBe(true);
  });

  it('对已软删用户再操作按「不存在」处理（40409）', async () => {
    await adminApi.deleteUser(2);

    await expect(adminApi.updateUser(2, { displayName: 'x' })).rejects.toMatchObject({
      code: 40409,
    });
    await expect(adminApi.deleteUser(2)).rejects.toMatchObject({ code: 40409 });
  });

  it('ApiError 带出 code，前端能按码做行内提示', async () => {
    const error = await adminApi
      .createUser({ username: 'u01', password: 'a-sufficient-password' })
      .catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe(40905);
  });
});

describe('登录响应带角色', () => {
  beforeEach(() => {
    resetMockUsers();
  });

  it('admin 登录拿到 ADMIN，其他账号拿到 USER', async () => {
    const adminLogin = await authApi.login({ username: 'admin', password: 'x' });
    expect(adminLogin.user.role).toBe('ADMIN');

    const userLogin = await authApi.login({ username: 'u01', password: 'x' });
    expect(userLogin.user.role).toBe('USER');
  });

  it('登录会把角色写进 localStorage，供路由守卫读', async () => {
    await authApi.login({ username: 'admin', password: 'x' });
    expect(window.localStorage.getItem('xiaoyi.role')).toBe('ADMIN');
  });

  it('profile 也能校准角色', async () => {
    const profile = await authApi.fetchProfile();
    expect(profile.role).toBe('USER');
  });
});
