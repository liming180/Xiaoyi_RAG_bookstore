import { computed, ref, shallowRef } from 'vue';
import { chatApi } from '@/api';
import { AbortStreamError } from '@/api/sse';
import type { AnswerMode, ChatStreamEvent, Citation, Message } from '@/types/api';
import {
  abort as abortState,
  failWith,
  initialState,
  pendingLabel,
  reduce,
  type ChatMachineState,
} from './chatMachine';

/**
 * useChat —— 发送链路（P3-B）。
 *
 * 职责边界：
 *  - 管一次问答的生命周期（发送 → 流式 → 落库 → 错误/中断）
 *  - 不直接改消息列表：通过 onPersist 回调交给 useConversation
 *
 * 状态机是纯函数（chatMachine.ts），这里只做副作用编排。
 */
export interface UseChatOptions {
  conversationId: () => string | null | undefined;
  /** 流结束后把落库版消息交给上层（替换流式占位） */
  onPersist?: (message: Message, directMessage?: Message | null) => void;
}

export function useChat(options: UseChatOptions) {
  const state = ref<ChatMachineState>(initialState());
  const sending = ref(false);
  /** 用户问题（用于流式占位气泡与重试） */
  const question = ref('');
  const controller = shallowRef<AbortController | null>(null);

  const pending = computed(() => pendingLabel(state.value));
  const draft = computed(() => state.value.draft);
  const citations = computed<Citation[]>(() => state.value.citations);
  const isStreaming = computed(() => state.value.phase === 'streaming');

  /** 流式期间的临时助手消息（渲染层直接吃这个） */
  const streamingMessage = computed<Message | null>(() => {
    const s = state.value;
    if (s.phase !== 'streaming') return null;
    if (!s.draft && !s.citations.length) return null;
    return {
      id: 'streaming',
      conversationId: options.conversationId() ?? '',
      role: 'assistant',
      content: s.draft,
      createdAt: Date.now(),
      citations: s.citations,
      trace: s.trace,
      usage: null,
      elapsedMs: null,
      degraded: false,
      suggestions: [],
      feedback: null,
    };
  });

  function reset(): void {
    state.value = initialState();
    question.value = '';
  }

  /** 把流式结果落成真实消息对象（后端已落库时优先用后端 id） */
  function toMessage(s: ChatMachineState): Message {
    return {
      id: s.messageId ?? `local-${Date.now()}`,
      conversationId: options.conversationId() ?? '',
      role: 'assistant',
      content: s.draft,
      createdAt: Date.now(),
      citations: s.citations,
      trace: s.trace,
      usage: null,
      elapsedMs: s.elapsedMs,
      degraded: s.degraded,
      suggestions: s.suggestions,
      feedback: null,
    };
  }

  async function send(text: string, mode: AnswerMode, k: number): Promise<boolean> {
    const q = text.trim();
    const cid = options.conversationId();
    if (!q || !cid || sending.value) return false;

    reset();
    question.value = q;
    sending.value = true;
    state.value = { ...state.value, phase: 'streaming' };
    const ctrl = new AbortController();
    controller.value = ctrl;

    try {
      for await (const event of chatApi.streamAnswer({
        conversationId: cid,
        question: q,
        mode,
        k,
        signal: ctrl.signal,
      })) {
        state.value = reduce(state.value, event as ChatStreamEvent);
        if (state.value.phase === 'error') break;
      }

      if (state.value.phase === 'done') {
        // F08：SSE 只带 citations，检索过程（候选全集 + 前 k 界线）在落库后
        // 按 messageId 单独拉。不补这一步的话，本次回答的 trace 永远是 null，
        // 页面上会显示上一条消息的检索过程 —— 看起来像「k 设置没生效」。
        if (state.value.messageId) {
          try {
            const trace = await chatApi.fetchTrace(state.value.messageId);
            if (trace) state.value = { ...state.value, trace };
          } catch {
            // trace 是增强信息，取不到不影响回答本身
          }
        }
        const persisted = toMessage(state.value);
        options.onPersist?.(persisted, null);
        return true;
      }
      return false;
    } catch (err) {
      if (err instanceof AbortStreamError) {
        state.value = abortState(state.value);
        return false;
      }
      const message = err instanceof Error ? err.message : '网络异常，请重试';
      state.value = failWith(state.value, message);
      return false;
    } finally {
      sending.value = false;
      controller.value = null;
    }
  }

  /** 生成中可点停止（F04） */
  function stop(): void {
    controller.value?.abort();
    state.value = abortState(state.value);
    sending.value = false;
  }

  return {
    state,
    sending,
    question,
    pending,
    draft,
    citations,
    isStreaming,
    streamingMessage,
    send,
    stop,
    reset,
  };
}
