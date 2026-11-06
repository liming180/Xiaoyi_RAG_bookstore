import type { LoginRequest, LoginResult, UserInfo } from '@/types/api';
import { get, post, setToken } from '../http';

/** 使用部署或测试初始化创建的账号登录，换取真实 JWT。 */
export async function login(payload: LoginRequest): Promise<LoginResult> {
  const result = await post<LoginResult>('/auth/login', payload);
  if (result?.token) setToken(result.token);
  return result;
}

/** 当前用户 */
export async function fetchProfile(): Promise<UserInfo> {
  return get<UserInfo>('/auth/profile');
}

export function logout(): void {
  setToken(null);
}
