import type {
  AnswerMode,
  ChatRequest,
  ChatStreamEvent,
  Citation,
  Conversation,
  Message,
  RetrievalTrace,
} from '@/types/api';
import { del, get, post } from '../http';
import { normalizeCitation, normalizeMessages, normalizeTrace } from '../normalize';
import { streamChat } from '../sse';

const BASE = import.meta.env.VITE_API_BASE ?? '/api/v1';

/* ---------------------------------------------------------------- 会话 */

export async function listConversations(): Promise<Conversation[]> {
  const raw = await get<unknown>('/conversations');
  const items = Array.isArray(raw) ? raw : ((raw as { items?: unknown[] })?.items ?? []);
  return items.map((item, i) => {
    const o = (item ?? {}) as Record<string, unknown>;
    return {
      id: String(o.id ?? o.conversationId ?? `c-${i + 1}`),
      title: String(o.title ?? '新会话'),
      createdAt: Number(o.createdAt ?? o.created_at ?? Date.now()),
      updatedAt: Number(o.updatedAt ?? o.updated_at ?? Date.now()),
      messageCount: Number(o.messageCount ?? o.message_count ?? 0),
    } satisfies Conversation;
  });
}

/**
 * 新建会话。
 *
 * 参数同时接受字符串与 `{ title }` 对象：store 侧历史上传的是对象
 * （`conversations.create` 调 `createConversation({ title })`），而函数签名
 * 只声明了字符串，于是请求体变成 `{"title":{"title":"新会话"}}`，真实后端按
 * `CreateConversationRequest(String title)` 反序列化失败回 400/40001 —— MSW 的
 * handler 用 `body.title ?? '新会话'` 把对象原样塞进 title，所以 mock 门禁一直是绿的。
 * 这里统一归一化，两种调用方式都发 `{"title":"..."}`。
 */
export async function createConversation(
  input: string | { title?: string } = '新会话',
): Promise<Conversation> {
  const rawTitle = typeof input === 'string' ? input : input?.title;
  const title = typeof rawTitle === 'string' && rawTitle.trim() ? rawTitle.trim() : '新会话';
  const o = (await post<Record<string, unknown>>('/conversations', { title })) ?? {};
  return {
    id: String(o.id ?? o.conversationId ?? ''),
    title: String(o.title ?? title),
    createdAt: Number(o.createdAt ?? Date.now()),
    updatedAt: Number(o.updatedAt ?? Date.now()),
    messageCount: Number(o.messageCount ?? 0),
  };
}

export async function deleteConversation(id: string): Promise<void> {
  await del<void>(`/conversations/${encodeURIComponent(id)}`);
}

/* ---------------------------------------------------------------- 消息 */

export async function listMessages(conversationId: string): Promise<Message[]> {
  const raw = await get<unknown>(`/conversations/${encodeURIComponent(conversationId)}/messages`);
  const items = Array.isArray(raw) ? raw : ((raw as { items?: unknown[] })?.items ?? []);
  return normalizeMessages(items);
}

/** F10 清空对话：清空服务端消息，保留会话与参数 */
export async function clearMessages(conversationId: string): Promise<void> {
  await del<void>(`/conversations/${encodeURIComponent(conversationId)}/messages`);
}

/** F08 检索过程（消息落库后按 id 拉全量 trace） */
export async function fetchTrace(messageId: string): Promise<RetrievalTrace | null> {
  const raw = await get<unknown>(`/messages/${encodeURIComponent(messageId)}/trace`);
  return normalizeTrace(raw);
}

/* ------------------------------------------------------------ SSE 对话 */

export interface StreamChatOptions {
  conversationId: string;
  question: string;
  mode: AnswerMode;
  k: number;
  signal?: AbortSignal;
}

/** 流式提问：产出 status/retrieval/token/done/error 事件 */
export function streamAnswer(options: StreamChatOptions): AsyncGenerator<ChatStreamEvent> {
  const body: ChatRequest = {
    conversationId: options.conversationId,
    question: options.question,
    mode: options.mode,
    k: options.k,
  };
  return streamChat(`${BASE}/chat/stream`, body, options.signal);
}

/** 从 retrieval 事件里取 citations（兼容两种字段形状） */
export function citationsFromEvent(data: unknown): Citation[] {
  const list = (data as { citations?: unknown })?.citations;
  if (!Array.isArray(list)) return [];
  return list.map((item, i) => normalizeCitation(item, i));
}
