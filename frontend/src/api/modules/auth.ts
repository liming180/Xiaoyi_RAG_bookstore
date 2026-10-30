import type { LoginRequest, LoginResult, UserInfo } from '@/types/api';
import { get, post, setToken } from '../http';

/** 登录（阶段1 演示模式由后端放行任意账密） */
export async function login(payload: LoginRequest): Promise<LoginResult> {
  const result = await post<LoginResult>('/auth/login', payload);
  if (result?.token) setToken(result.token);
  return result;
}

/** 演示模式一键进入：不传账密，后端返回访客 token */
export async function loginAsDemo(): Promise<LoginResult> {
  const result = await post<LoginResult>('/auth/login', { username: 'demo', password: 'demo' });
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
