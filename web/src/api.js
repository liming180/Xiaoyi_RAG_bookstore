/**
 * 统一的 fetch 封装 —— 与旧版 web/legacy/app.js:29 的 api() 行为一致：
 *   1. body 不是 FormData 时自动 JSON.stringify 并补 Content-Type；
 *   2. 响应一律按 JSON 解析（解析失败按空对象处理）；
 *   3. 非 2xx 时优先抛出后端 {detail}，否则用「请求失败（HTTP 状态码）」。
 */
export async function api(path, options = {}) {
  const init = { ...options, headers: { ...(options.headers || {}) } };
  if (init.body && !(init.body instanceof FormData)) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(init.body);
  }
  const resp = await fetch(path, init);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.detail || `请求失败（HTTP ${resp.status}）`);
  }
  return data;
}

export const http = {
  get: (path) => api(path),
  post: (path, body) => api(path, { method: 'POST', body }),
  del: (path) => api(path, { method: 'DELETE' }),
};
