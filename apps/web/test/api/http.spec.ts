import { describe, expect, it, vi } from 'vitest';
import { HttpResponse, http as mswHttp } from 'msw';
import { server } from '@/mocks/node';
import { ApiError, get, post, setToken, getToken } from '@/api/http';
import { on } from '@/api/events';

describe('http 层：Result 拆包', () => {
  it('code === 0 时直接返回 data', async () => {
    server.use(
      mswHttp.get('/api/v1/ping', () =>
        HttpResponse.json({ code: 0, message: 'success', data: { pong: true }, timestamp: 1 }),
      ),
    );
    await expect(get<{ pong: boolean }>('/ping')).resolves.toEqual({ pong: true });
  });

  it('code !== 0 时抛出 ApiError 且带业务码', async () => {
    server.use(
      mswHttp.get('/api/v1/boom', () =>
        HttpResponse.json({ code: 40001, message: '参数不合法', data: null, timestamp: 1 }),
      ),
    );
    await expect(get('/boom')).rejects.toBeInstanceOf(ApiError);
    await expect(get('/boom')).rejects.toMatchObject({ code: 40001, message: '参数不合法' });
  });

  it('503 时广播 system:degraded 并抛错', async () => {
    const spy = vi.fn();
    const off = on('system:degraded', spy);
    server.use(
      mswHttp.get('/api/v1/chat/stream', () =>
        HttpResponse.json(
          { code: 50301, message: 'AI service unavailable', data: null, timestamp: 1 },
          { status: 503 },
        ),
      ),
    );
    await expect(get('/chat/stream')).rejects.toBeInstanceOf(ApiError);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy.mock.calls[0]?.[0]).toMatchObject({ message: 'AI service unavailable' });
    off();
  });

  it('401 时清 token 并广播 auth:expired', async () => {
    const spy = vi.fn();
    const off = on('auth:expired', spy);
    setToken('stale-token');
    expect(getToken()).toBe('stale-token');
    server.use(
      mswHttp.get('/api/v1/private', () =>
        HttpResponse.json(
          { code: 40100, message: '登录已过期', data: null, timestamp: 1 },
          { status: 401 },
        ),
      ),
    );
    await expect(get('/private')).rejects.toMatchObject({ code: 40100 });
    expect(getToken()).toBeNull();
    expect(spy).toHaveBeenCalledTimes(1);
    off();
  });

  it('请求头自动带 Bearer token', async () => {
    let seen: string | null = null;
    server.use(
      mswHttp.get('/api/v1/whoami', ({ request }) => {
        seen = request.headers.get('authorization');
        return HttpResponse.json({ code: 0, message: 'ok', data: {}, timestamp: 1 });
      }),
    );
    setToken('abc123');
    await get('/whoami');
    expect(seen).toBe('Bearer abc123');
  });

  it('post 透传请求体', async () => {
    let body: unknown = null;
    server.use(
      mswHttp.post('/api/v1/echo', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ code: 0, message: 'ok', data: { ok: 1 }, timestamp: 1 });
      }),
    );
    await post('/echo', { hello: 'world' });
    expect(body).toEqual({ hello: 'world' });
  });
});
