import type { RouteLocationNormalized } from 'vue-router';

/**
 * 路由守卫的纯判定层。
 *
 * 把「该不该放行」抽成不依赖 router 实例的纯函数，有两个直接好处：
 *   1. 守卫逻辑可以单测，不用起一整套 router + 组件；
 *   2. 登录页「已登录就别再进去」这类反向规则和白名单规则写在一处，不会散落。
 *
 * 规则：
 *   - meta.public === true 的页面（登录页）任何人可进；
 *   - 没有 token 一律回登录页，并带上 redirect，登录后能回到原来想去的地方；
 *   - 有 token 还去登录页 → 直接送进对话页，避免「已登录却停在登录页」。
 */
export type GuardDecision = true | { name: string; query?: Record<string, string> };

export function resolveNavigation(
  to: Pick<RouteLocationNormalized, 'fullPath' | 'meta'>,
  hasToken: boolean,
): GuardDecision {
  const isPublic = to.meta.public === true;

  if (isPublic) {
    if (hasToken) return { name: 'chat' };
    return true;
  }

  if (!hasToken) {
    // 只在目标不是根路径时才记 redirect，否则登录后会回到一个没意义的 `/`
    const query = to.fullPath && to.fullPath !== '/' ? { redirect: to.fullPath } : undefined;
    return query ? { name: 'login', query } : { name: 'login' };
  }

  return true;
}

/**
 * 登录成功后该跳去哪。
 *
 * 只接受站内相对路径：`redirect` 来自 query，属于用户可控输入，
 * 直接拿来 `router.push` 会让 `//evil.com` 这类值变成站外跳转。
 */
export function safeRedirect(raw: unknown, fallback = '/chat'): string {
  if (typeof raw !== 'string') return fallback;
  if (!raw.startsWith('/')) return fallback;
  if (raw.startsWith('//')) return fallback;
  return raw;
}
