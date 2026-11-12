import type { UserRole } from '@/types/api';

/**
 * 角色持久化。
 *
 * 为什么单独存一份而不是每次调 /auth/profile：路由守卫在**每次导航**都会跑，守卫里发网络请求
 * 会变成「切页面先等一个 RTT」。role 属于登录态的一部分，与 token 同生命周期（登录写入、
 * 登出/401 清空），放 localStorage 里读一次是常数时间。
 *
 * 唯一风险是「本地 role 被改高」——那是纯前端把戏：真正的闸门在服务端
 * AdminInterceptor，非 ADMIN 的 token 调 /admin/** 一律 403。
 */
export const ROLE_KEY = 'xiaoyi.role';

export function getRole(): UserRole | null {
  try {
    const raw = window.localStorage.getItem(ROLE_KEY);
    return raw === 'ADMIN' || raw === 'USER' ? raw : null;
  } catch {
    return null;
  }
}

export function setRole(role: UserRole | null): void {
  try {
    if (role) window.localStorage.setItem(ROLE_KEY, role);
    else window.localStorage.removeItem(ROLE_KEY);
  } catch {
    /* 隐私模式忽略 */
  }
}

/** 当前会话是否是管理员。 */
export function isAdmin(): boolean {
  return getRole() === 'ADMIN';
}
