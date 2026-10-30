import { describe, expect, it } from 'vitest';
import { createSseParser, toChatEvent } from '@/api/sse';
import type { ChatStreamEvent } from '@/types/api';

const collect = (chunks: string[]): string[] => {
  const parser = createSseParser();
  const out: string[] = [];
  for (const chunk of chunks) {
    for (const frame of parser.push(chunk)) out.push(`${frame.event}:${frame.data}`);
  }
  for (const frame of parser.flush()) out.push(`${frame.event}:${frame.data}`);
  return out;
};

describe('SSE 帧解析', () => {
  it('解析单帧 status 事件', () => {
    const parser = createSseParser();
    const frames = parser.push('event: status\ndata: {"stage":"retrieving"}\n\n');
    expect(frames).toHaveLength(1);
    expect(frames[0]).toEqual({ event: 'status', data: '{"stage":"retrieving"}' });
  });

  it('处理半包：帧跨多个 chunk', () => {
    const out = collect(['event: tok', 'en\ndata: {"content":"你', '好"}\n\n']);
    expect(out).toEqual(['token:{"content":"你好"}']);
  });

  it('处理粘包：一个 chunk 里多帧', () => {
    const out = collect([
      'event: status\ndata: {"stage":"retrieving"}\n\nevent: token\ndata: {"content":"根"}\n\n',
    ]);
    expect(out).toHaveLength(2);
    expect(out[0]).toBe('status:{"stage":"retrieving"}');
    expect(out[1]).toBe('token:{"content":"根"}');
  });

  it('兼容 CRLF 分隔符', () => {
    const out = collect(['event: done\r\ndata: {"messageId":1}\r\n\r\n']);
    expect(out).toEqual(['done:{"messageId":1}']);
  });

  it('忽略注释行（keep-alive）', () => {
    const out = collect([': keep-alive\n\nevent: token\ndata: {"content":"a"}\n\n']);
    expect(out).toEqual(['token:{"content":"a"}']);
  });

  it('多行 data 用换行拼接', () => {
    const parser = createSseParser();
    const frames = parser.push('event: token\ndata: line1\ndata: line2\n\n');
    expect(frames[0]?.data).toBe('line1\nline2');
  });

  it('flush 吐出末尾不完整帧', () => {
    const parser = createSseParser();
    expect(parser.push('event: done\ndata: {"a":1}')).toHaveLength(0);
    expect(parser.flush()).toEqual([{ event: 'done', data: '{"a":1}' }]);
  });

  it('未知事件原样透传，不抛错', () => {
    const event = toChatEvent({ event: 'heartbeat', data: '{"t":1}' }) as ChatStreamEvent;
    expect(event.event).toBe('heartbeat');
    expect((event.data as { t: number }).t).toBe(1);
  });

  it('非法 JSON 的 data 降级为字符串', () => {
    const event = toChatEvent({ event: 'token', data: 'not-json' });
    expect(event.data).toBe('not-json');
  });
});
