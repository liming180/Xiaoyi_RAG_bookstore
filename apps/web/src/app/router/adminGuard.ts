import type { RouteLocationNormalized } from 'vue-router';
import type { GuardDecision } from './guard';

/**
 * 管理端分区的守卫判定（纯函数，便于单测）。
 *
 * 规则只有一条：`meta.requiresAdmin === true` 的页面要求「有 token **且** 是 ADMIN」，
 * 否则送回对话页。
 *
 * 为什么非管理员不是送回登录页：他已经登录了，只是没权限。送回登录页会让人误以为
 * 会话失效，还会盖掉真正的错误原因。回对话页 + 一句提示更准确。
 *
 * 注意这里只做**前端**拦截，作用是「别让人白点进去看一片 403」。真正的权限边界在服务端的
 * AdminInterceptor —— 前端把 role 改成 ADMIN 也调不动管理接口。
 */
export function resolveAdminNavigation(
  to: Pick<RouteLocationNormalized, 'meta'>,
  hasToken: boolean,
  isAdminRole: boolean,
): GuardDecision {
  if (to.meta.requiresAdmin === true && (!hasToken || !isAdminRole)) {
    return { name: 'chat' };
  }
  return true;
}
