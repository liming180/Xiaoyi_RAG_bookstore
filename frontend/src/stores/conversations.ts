import { defineStore } from 'pinia';
import { ref } from 'vue';
import { chatApi } from '@/api';
import { STORAGE_KEYS } from '@/constants/app';
import { readStorage, writeStorage } from '@/utils/storage';
import type { Conversation } from '@/types/api';

/**
 * 会话列表（客户端导航状态）。
 *
 * 只保存「当前选中哪个会话」与「会话摘要列表」这类 UI 需要跨组件共享的状态，
 * 消息正文不进 Pinia —— 消息属于服务端数据，由对话页自己按需拉取。
 */
export const useConversationsStore = defineStore('conversations', () => {
  const list = ref<Conversation[]>([]);
  const activeId = ref<string | null>(readStorage(STORAGE_KEYS.conversationId));
  const loading = ref(false);
  const error = ref<string | null>(null);

  function setActive(id: string | null): void {
    activeId.value = id;
    if (id) writeStorage(STORAGE_KEYS.conversationId, id);
  }

  async function fetchList(): Promise<void> {
    loading.value = true;
    try {
      const next = await chatApi.listConversations();
      list.value = next;
      error.value = null;
      if (!activeId.value || !next.some((c) => c.id === activeId.value)) {
        setActive(next[0]?.id ?? null);
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
    } finally {
      loading.value = false;
    }
  }

  async function create(title = '新会话'): Promise<Conversation | null> {
    try {
      const conv = await chatApi.createConversation({ title });
      list.value = [conv, ...list.value];
      setActive(conv.id);
      return conv;
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
      return null;
    }
  }

  async function remove(id: string): Promise<void> {
    await chatApi.deleteConversation(id);
    list.value = list.value.filter((c) => c.id !== id);
    if (activeId.value === id) setActive(list.value[0]?.id ?? null);
  }

  return { list, activeId, loading, error, setActive, fetchList, create, remove };
});
