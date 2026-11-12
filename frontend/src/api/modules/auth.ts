import type { LoginRequest, LoginResult, UserInfo } from '@/types/api';
import { setRole } from '@/app/router/role';
import { get, post, setToken } from '../http';

/**
 * 使用部署或测试初始化创建的账号登录，换取真实 JWT。
 *
 * 角色（`ADMIN` / `USER`）随登录结果一起落 localStorage，供路由守卫在下一次导航时读：
 * 管理员进管理端，普通用户进对话页。
 */
export async function login(payload: LoginRequest): Promise<LoginResult> {
  const result = await post<LoginResult>('/auth/login', payload);
  if (result?.token) setToken(result.token);
  if (result?.user?.role) setRole(result.user.role);
  return result;
}

/** 当前用户。刷新页面后用它校准本地角色（本地值可能是旧版本的、或被人为改过）。 */
export async function fetchProfile(): Promise<UserInfo> {
  const profile = await get<UserInfo>('/auth/profile');
  if (profile?.role) setRole(profile.role);
  return profile;
}

/** 退出登录：token 与角色一起清，避免「换个账号登录却还带着上一个账号的管理端入口」。 */
export function logout(): void {
  setToken(null);
  setRole(null);
}
