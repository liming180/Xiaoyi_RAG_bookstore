import axios, { type AxiosInstance, type AxiosRequestConfig, type AxiosResponse } from 'axios';
import type { Result } from '@/types/api';
import { emit } from './events';

/** 业务错误：code !== 0 或 HTTP 非 2xx */
export class ApiError extends Error {
  readonly code: number;
  readonly httpStatus: number;
  readonly payload: unknown;

  constructor(code: number, message: string, httpStatus = 0, payload: unknown = null) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.httpStatus = httpStatus;
    this.payload = payload;
  }
}

export const TOKEN_KEY = 'xiaoyi.token';

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* 隐私模式忽略 */
  }
}

const BASE_URL = import.meta.env.VITE_API_BASE ?? '/api/v1';

export const http: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

/* ------------------------------------------------------- 请求拦截：注入 JWT */
http.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.set?.('Authorization', `Bearer ${token}`);
  }
  return config;
});

/* --------------------------------- 响应拦截：拆包 Result<T> + 统一错误语义 */
http.interceptors.response.use(
  (response: AxiosResponse) => {
    const body = response.data as Result<unknown> | undefined;

    // 非 Result 包装（例如 SSE 或第三方直返），原样返回
    if (!body || typeof body !== 'object' || !('code' in body)) {
      return response;
    }

    if (body.code === 0) {
      return { ...response, data: body.data };
    }

    // 业务错误码
    throw new ApiError(body.code, body.message || '请求失败', response.status, body.data);
  },
  (error: unknown) => {
    if (axios.isCancel(error)) throw error;

    if (axios.isAxiosError(error)) {
      const status = error.response?.status ?? 0;
      const body = error.response?.data as Result<unknown> | undefined;
      const code = typeof body?.code === 'number' ? body.code : status || -1;
      const message = body?.message || error.message || '网络错误';

      if (status === 401) {
        setToken(null);
        emit('auth:expired', undefined);
      }
      if (status === 503) {
        emit('system:degraded', { code, message });
      }
      throw new ApiError(code, message, status, body?.data ?? null);
    }

    throw new ApiError(-1, error instanceof Error ? error.message : '未知错误', 0, null);
  },
);

/* ------------------------------------------------ 类型安全的调用包装函数 */

export async function get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const res = await http.get<T>(url, config);
  return res.data;
}

export async function post<T>(
  url: string,
  body?: unknown,
  config?: AxiosRequestConfig,
): Promise<T> {
  const res = await http.post<T>(url, body, config);
  return res.data;
}

export async function put<T>(url: string, body?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const res = await http.put<T>(url, body, config);
  return res.data;
}

export async function del<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const res = await http.delete<T>(url, config);
  return res.data;
}

/** 文件上传：不手动设置 Content-Type，交给浏览器补 boundary */
export async function upload<T>(url: string, form: FormData, config?: AxiosRequestConfig): Promise<T> {
  const res = await http.post<T>(url, form, {
    ...config,
    headers: { ...config?.headers, 'Content-Type': undefined },
  });
  return res.data;
}
