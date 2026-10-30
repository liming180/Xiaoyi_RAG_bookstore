import { computed, ref, watch } from 'vue';
import { chatApi } from '@/api';
import type { Citation, Message } from '@/types/api';

/**
 * useConversation —— 单个会话的消息装载（P3-A）。
 *
 * 只负责「读」：拉历史消息、暴露 loading/error、提供本地增删。
 * 发送链路在 useChat（P3-B），两者通过 messages 数组协作。
 *
 * 服务端数据不进 Pinia —— 这里用组件级 ref，符合架构铁律。
 */
export function useConversation(conversationId: () => string | null | undefined) {
  const messages = ref<Message[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  /** 防止并发加载把旧结果覆盖到新会话上 */
  let loadToken = 0;

  const lastAssistant = computed<Message | null>(() => {
    for (let i = messages.value.length - 1; i >= 0; i -= 1) {
      const m = messages.value[i];
      if (m && m.role === 'assistant') return m;
    }
    return null;
  });

  const isEmpty = computed(() => messages.value.length === 0);

  /** 最近一次提问（F08 检索过程面板的表头） */
  const lastQuestion = computed(() => {
    for (let i = messages.value.length - 1; i >= 0; i -= 1) {
      const m = messages.value[i];
      if (m && m.role === 'user') return m.content;
    }
    return '';
  });

  async function load(): Promise<void> {
    const id = conversationId();
    if (!id) {
      messages.value = [];
      return;
    }
    const token = ++loadToken;
    loading.value = true;
    error.value = null;
    try {
      const list = await chatApi.listMessages(id);
      if (token !== loadToken) return;
      messages.value = list;
    } catch (e) {
      if (token !== loadToken) return;
      error.value = e instanceof Error ? e.message : '加载对话失败';
      messages.value = [];
    } finally {
      if (token === loadToken) loading.value = false;
    }
  }

  function append(message: Message): void {
    messages.value.push(message);
  }

  /** 用落库版替换流式版（done 后调用） */
  function replace(messageId: string, next: Message): void {
    const idx = messages.value.findIndex((m) => m.id === messageId);
    if (idx >= 0) messages.value.splice(idx, 1, next);
    else messages.value.push(next);
  }

  function clear(): void {
    messages.value = [];
  }

  /** 全部引用（去重，按 ref 升序）—— 供引用面板/未核实提醒汇总 */
  const allCitations = computed<Citation[]>(() => {
    const seen = new Set<string>();
    const out: Citation[] = [];
    for (const m of messages.value) {
      for (const c of m.citations) {
        const key = `${String(c.ref)}::${c.chunkId}`;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push(c);
      }
    }
    return out.sort((a, b) => {
      const ra = typeof a.ref === 'number' ? a.ref : Number.MAX_SAFE_INTEGER;
      const rb = typeof b.ref === 'number' ? b.ref : Number.MAX_SAFE_INTEGER;
      return ra - rb;
    });
  });

  const hasUnverified = computed(() => allCitations.value.some((c) => !c.verified));

  watch(conversationId, () => void load(), { immediate: true });

  return {
    messages,
    loading,
    error,
    isEmpty,
    lastAssistant,
    lastQuestion,
    allCitations,
    hasUnverified,
    load,
    append,
    replace,
    clear,
  };
}
