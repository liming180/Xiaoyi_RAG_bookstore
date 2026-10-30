import type { ChatStreamEvent } from '@/types/api';
import { getToken } from './http';

/**
 * SSE 帧解析器（纯函数，可单测）
 *
 * 需要处理的真实网络情况：
 *  - 一帧跨多个 chunk（半包）：必须保留 remainder 到下次 push
 *  - 一个 chunk 里有多帧（粘包）：必须一次吐出全部完整帧
 *  - 帧分隔符 CRLF / LF / CR 三种都要认
 *  - 以 ':' 开头的是注释行（keep-alive），必须忽略
 *  - data: 可以出现多次，按 '\n' 拼接
 */
export interface SseFrame {
  event: string;
  data: string;
}

export interface SseParser {
  push(chunk: string): SseFrame[];
  flush(): SseFrame[];
}

const FRAME_SEP = /\r\n\r\n|\n\n|\r\r/;

function parseFrame(raw: string): SseFrame | null {
  let event = 'message';
  const dataLines: string[] = [];
  let hasField = false;

  for (const line of raw.split(/\r\n|\n|\r/)) {
    if (line === '' || line.startsWith(':')) continue;
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);

    if (field === 'event') {
      event = value;
      hasField = true;
    } else if (field === 'data') {
      dataLines.push(value);
      hasField = true;
    }
  }

  if (!hasField) return null;
  return { event, data: dataLines.join('\n') };
}

export function createSseParser(): SseParser {
  let buffer = '';

  const drain = (): SseFrame[] => {
    const frames: SseFrame[] = [];
    let match = FRAME_SEP.exec(buffer);
    while (match) {
      const raw = buffer.slice(0, match.index);
      buffer = buffer.slice(match.index + match[0].length);
      const frame = parseFrame(raw);
      if (frame) frames.push(frame);
      match = FRAME_SEP.exec(buffer);
    }
    return frames;
  };

  return {
    push(chunk: string): SseFrame[] {
      buffer += chunk;
      return drain();
    },
    flush(): SseFrame[] {
      const rest = buffer;
      buffer = '';
      if (rest.trim() === '') return [];
      const frame = parseFrame(rest);
      return frame ? [frame] : [];
    },
  };
}

/** 把原始帧转成强类型的领域事件；未知事件原样透传（不抛错） */
export function toChatEvent(frame: SseFrame): ChatStreamEvent {
  let parsed: unknown = frame.data;
  try {
    parsed = frame.data === '' ? {} : JSON.parse(frame.data);
  } catch {
    parsed = frame.data;
  }
  return { event: frame.event, data: parsed } as ChatStreamEvent;
}

export class AbortStreamError extends Error {
  constructor() {
    super('stream aborted');
    this.name = 'AbortError';
  }
}

/**
 * 发起流式对话，逐个产出领域事件。
 *
 * 用 fetch 而不是 EventSource：需要 POST + 请求体 + Authorization 头。
 */
export async function* streamChat(
  url: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent, void, unknown> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body), signal });
  } catch (err) {
    if ((err as Error)?.name === 'AbortError') throw new AbortStreamError();
    throw err;
  }

  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    let code = response.status;
    try {
      const text = await response.text();
      const parsed = JSON.parse(text) as { code?: number; message?: string };
      if (typeof parsed.message === 'string') message = parsed.message;
      if (typeof parsed.code === 'number') code = parsed.code;
    } catch {
      /* 非 JSON 错误体，用状态码兜底 */
    }
    const err = new Error(message) as Error & { code: number };
    err.code = code;
    throw err;
  }

  if (!response.body) throw new Error('响应体为空，无法读取流');

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  const parser = createSseParser();

  /**
   * 中断兜底：某些环境里 reader.read() 在 abort 后既不 resolve 也不 reject，
   * 会把 for-await 挂死。这里用 Promise.race 抢一个显式的中止信号。
   */
  const aborted = new Promise<never>((_, reject) => {
    if (!signal) return;
    if (signal.aborted) reject(new AbortStreamError());
    signal.addEventListener('abort', () => reject(new AbortStreamError()), { once: true });
  });
  // 没有 signal 时给一个永不 settle 的占位，避免 unhandled rejection
  aborted.catch(() => undefined);

  try {
    for (;;) {
      if (signal?.aborted) throw new AbortStreamError();
      const { done, value } = await Promise.race([reader.read(), aborted]);
      if (done) break;
      const text = decoder.decode(value, { stream: true });
      for (const frame of parser.push(text)) {
        yield toChatEvent(frame);
      }
    }
    for (const frame of parser.flush()) {
      yield toChatEvent(frame);
    }
  } catch (err) {
    if ((err as Error)?.name === 'AbortError') throw new AbortStreamError();
    throw err;
  } finally {
    // 不 await：某些 polyfill 的 cancel() 在中止后永不 settle，会把调用方挂死
    void reader.cancel().catch(() => undefined);
  }
}
