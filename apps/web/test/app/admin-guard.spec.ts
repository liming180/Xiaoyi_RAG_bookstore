import { beforeEach, describe, expect, it } from 'vitest';
import { resolveAdminNavigation } from '@/app/router/adminGuard';
import { getRole, isAdmin, ROLE_KEY, setRole } from '@/app/router/role';

/**
 * 管理端守卫与角色存储（06 号设计方案 §9.3）。
 *
 * 这里只测**判定逻辑**：真正的权限边界在服务端 AdminInterceptor，
 * 前端守卫的作用是「别让人白点进去看一片 403」。
 */
describe('管理端路由守卫', () => {
  it('ADMIN 访问受限页面放行', () => {
    expect(resolveAdminNavigation({ meta: { requiresAdmin: true } }, true, true)).toBe(true);
  });

  it('普通用户被弹回对话页（不是登录页：他已经登录了）', () => {
    expect(resolveAdminNavigation({ meta: { requiresAdmin: true } }, true, false)).toEqual({
      name: 'chat',
    });
  });

  it('未登录被弹回对话页，由普通守卫先拦到登录页', () => {
    expect(resolveAdminNavigation({ meta: { requiresAdmin: true } }, false, false)).toEqual({
      name: 'chat',
    });
  });

  it('本地角色被改成 ADMIN 但没 token 也不放行', () => {
    expect(resolveAdminNavigation({ meta: { requiresAdmin: true } }, false, true)).toEqual({
      name: 'chat',
    });
  });

  it('不要求管理员的页面一律放行', () => {
    expect(resolveAdminNavigation({ meta: {} }, true, false)).toBe(true);
    expect(resolveAdminNavigation({ meta: {} }, true, true)).toBe(true);
  });
});

describe('角色持久化', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('默认没有角色', () => {
    expect(getRole()).toBeNull();
    expect(isAdmin()).toBe(false);
  });

  it('写入后能读回，isAdmin 只在 ADMIN 时为真', () => {
    setRole('ADMIN');
    expect(getRole()).toBe('ADMIN');
    expect(isAdmin()).toBe(true);

    setRole('USER');
    expect(getRole()).toBe('USER');
    expect(isAdmin()).toBe(false);
  });

  it('清空后回到未登录状态（登出与 401 都走这条路径）', () => {
    setRole('ADMIN');
    setRole(null);
    expect(getRole()).toBeNull();
    expect(window.localStorage.getItem(ROLE_KEY)).toBeNull();
  });

  it('本地值被改脏时按未登录处理，不会因为脏数据变成管理员', () => {
    window.localStorage.setItem(ROLE_KEY, 'SUPERADMIN');
    expect(getRole()).toBeNull();
    expect(isAdmin()).toBe(false);
  });
});
