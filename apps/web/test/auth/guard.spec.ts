import { describe, expect, it } from 'vitest';
import { resolveNavigation, safeRedirect } from '@/app/router/guard';

/**
 * 路由守卫（P6）。
 *
 * 只测纯判定层：真实 router 的导航行为由浏览器冒烟脚本覆盖，
 * 这里要保证的是「什么情况下放行、什么情况下踢回登录」这条规则本身没有漏洞。
 */

function route(fullPath: string, meta: Record<string, unknown> = {}) {
  return { fullPath, meta } as Parameters<typeof resolveNavigation>[0];
}

describe('路由守卫', () => {
  it('未登录访问业务页 → 踢回登录页并记住来源', () => {
    expect(resolveNavigation(route('/chat'), false)).toEqual({
      name: 'login',
      query: { redirect: '/chat' },
    });
  });

  it('未登录访问带参数的深链 → redirect 保留完整路径与 query', () => {
    expect(resolveNavigation(route('/knowledge/chunks?chunk_id=D02-C002'), false)).toEqual({
      name: 'login',
      query: { redirect: '/knowledge/chunks?chunk_id=D02-C002' },
    });
  });

  it('未登录访问根路径 → 不写无意义的 redirect', () => {
    expect(resolveNavigation(route('/'), false)).toEqual({ name: 'login' });
  });

  it('已登录访问业务页 → 放行', () => {
    expect(resolveNavigation(route('/eval'), true)).toBe(true);
  });

  it('登录页对未登录用户开放', () => {
    expect(resolveNavigation(route('/login', { public: true }), false)).toBe(true);
  });

  it('已登录再进登录页 → 直接送去对话页', () => {
    expect(resolveNavigation(route('/login', { public: true }), true)).toEqual({ name: 'chat' });
  });
});

describe('登录后跳转目标', () => {
  it('站内相对路径原样返回', () => {
    expect(safeRedirect('/knowledge?tab=1')).toBe('/knowledge?tab=1');
  });

  it('缺失或非字符串 → 回落对话页', () => {
    expect(safeRedirect(undefined)).toBe('/chat');
    expect(safeRedirect(['/eval'])).toBe('/chat');
    expect(safeRedirect(42)).toBe('/chat');
  });

  it('协议相对地址（//evil.com）不许当站内路径', () => {
    expect(safeRedirect('//evil.com/path')).toBe('/chat');
  });

  it('绝对外链不认', () => {
    expect(safeRedirect('https://evil.com')).toBe('/chat');
  });

  it('自定义回落值生效', () => {
    expect(safeRedirect(null, '/knowledge')).toBe('/knowledge');
  });
});
