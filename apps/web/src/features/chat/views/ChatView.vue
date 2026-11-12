<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import type { AnswerMode, Citation, Message } from '@/types/api';
import { SEED_EXAMPLES } from '@/mocks/data';
import { chatApi, evalApi } from '@/api';
import { useConversationsStore } from '@/stores/conversations';
import { useSystemStatusStore } from '@/stores/systemStatus';
import { useQueryPrefs } from '@/composables/useQueryPrefs';
import { useConversation } from '../composables/useConversation';
import { useChat } from '../composables/useChat';
import MessageList from '../components/MessageList.vue';
import ChatInput from '../components/ChatInput.vue';
import RetrievalTrace from '../components/RetrievalTrace.vue';
import ComparePane from '../components/ComparePane.vue';
import SuggestionChips from '../components/SuggestionChips.vue';

/**
 * ChatView —— 对话页（P3-C 完整版）。
 *
 * 覆盖 F04 对话 / F05 来源 / F06 三模式 / F07 取回数量 / F08 检索过程 / F10 清空。
 *
 * 数据流：
 *   ChatInput.send → useChat.send → SSE → chatMachine（纯函数）
 *   → streamingMessage（流式占位）/ compareDraft（对照右栏）
 *   → done 后 onPersist 追加落库消息
 */
const route = useRoute();
const router = useRouter();
const conversations = useConversationsStore();
const systemStatus = useSystemStatusStore();
const { mode, k, setMode, setK } = useQueryPrefs();

const conversationId = computed<string | null>(() => {
  const param = route.params.id;
  if (typeof param === 'string' && param) return param;
  return conversations.activeId;
});

const { messages, loading, error, append, clear, lastQuestion } = useConversation(
  () => conversationId.value,
);

const chat = useChat({
  conversationId: () => conversationId.value,
  onPersist: (message) => {
    append(message);
  },
});

const clearing = ref(false);
/** 正在把对照结果送进候选池 */
const capturing = ref(false);

/** 最近一条带 trace 的助手消息 → 检索过程面板 */
const traceForLast = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    const m = messages.value[i];
    if (m && m.role === 'assistant' && m.trace) return m.trace;
  }
  return null;
});

/** 对照模式：最近一轮的 rag 侧与 direct 侧 */
const compareRag = computed<Message | null>(() => {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    const m = messages.value[i];
    if (m && m.role === 'assistant' && !m.degraded) return m;
  }
  return null;
});

const compareDirect = computed<Message | null>(() => {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    const m = messages.value[i];
    if (m && m.role === 'assistant' && m.degraded) return m;
  }
  return null;
});

const showCompare = computed(() => mode.value === 'both' && messages.value.length > 0);
const showExamples = computed(() => messages.value.length === 0 && !chat.isStreaming.value);

function buildUserMessage(text: string): Message {
  return {
    id: `local-u-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    conversationId: conversationId.value ?? '',
    role: 'user',
    content: text,
    createdAt: Date.now(),
    citations: [],
    trace: null,
    usage: null,
    elapsedMs: null,
    degraded: false,
    suggestions: [],
    feedback: null,
  };
}

async function send(text: string): Promise<void> {
  const cid = conversationId.value;
  if (!cid || chat.sending.value) return;
  // 套餐 E3：实验期间后端对 POST /chat/stream 返回 409，前端提前拦下，
  // 避免用户白发一次请求才看到错误气泡。
  if (systemStatus.experimentRunning) {
    ElMessage.warning('参数实验进行中，提问暂不可用，请等实验完成');
    return;
  }

  append(buildUserMessage(text));
  const ok = await chat.send(text, mode.value, k.value);

  if (!ok && chat.state.value.phase === 'error' && chat.state.value.error) {
    append({
      id: `local-err-${Date.now()}`,
      conversationId: cid,
      role: 'assistant',
      content: chat.draft.value,
      createdAt: Date.now(),
      citations: chat.citations.value,
      trace: null,
      usage: null,
      elapsedMs: null,
      degraded: false,
      suggestions: [],
      feedback: null,
      error: chat.state.value.error.message,
    });
  }
}

/** 错误气泡上的重试：重发上一个问题 */
async function retry(): Promise<void> {
  const q = chat.question.value || lastQuestion.value;
  if (q) await send(q);
}

function onMode(value: AnswerMode): void {
  setMode(value);
}

function onK(value: number): void {
  setK(value);
}

/** F10 清空对话：确认后清服务端 + 本地，保留 mode/k */
async function onClear(): Promise<void> {
  const cid = conversationId.value;
  if (!cid || clearing.value) return;
  clearing.value = true;
  try {
    await chatApi.clearMessages(cid);
    clear();
    chat.reset();
    ElMessage.success('已清空本轮对话，提问设置已保留');
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '清空失败，请重试');
  } finally {
    clearing.value = false;
  }
}

function onOpenInKnowledge(citation: Citation): void {
  void router.push({
    name: 'chunks',
    query: { chunk_id: citation.chunkId, doc: citation.docTitle },
  });
}

/**
 * 对照模式里的引用角标（换肤）。
 *
 * 原行为：@cite 直接接到 onOpenInKnowledge，点角标就跳去知识库片段页 ——
 * 对照模式本来是用来「并排看两栏差别」的，一点角标就把人送出页面，很割裂。
 * 现在改为打开引用抽屉（与消息列表里的角标行为一致），抽屉里再给
 * 「在知识库中查看」作为显式出口。
 *
 * messageListRef 是 MessageList 暴露的 defineExpose，含 onCite / activeCitation。
 */
const messageListRef = ref<InstanceType<typeof MessageList> | null>(null);

function onCompareCite(citation: Citation): void {
  messageListRef.value?.onCite(citation);
}

/** C1：反馈已由 FeedbackBar 写回消息对象，这里只做「未核实」提示的联动 */
function onFeedback(messageId: string, rating: 'up' | 'down' | null): void {
  const target = messages.value.find((m) => m.id === messageId);
  if (target) target.feedback = rating;
}

/** 流式期间把临时消息塞给列表 */
const streaming = computed<Message | null>(() => chat.streamingMessage.value);

/**
 * 对照时发现差异 → 把这一问送进评测候选池。
 *
 * <p>这是 both 模式与评测体系的接缝：对照的目的是发现 badcase，发现之后必须能
 * 一键留痕，否则用户看完两栏只能截图记笔记。落进候选池后到「评测 → 候选题池」
 * 补判分关键词，就能进实验计分。
 *
 * <p>候选池的写入需要一条 messageId（候选是由 👎 反馈产生的）。这里没有走反馈
 * 通道，而是把 rag 侧的消息 id 借给后端 —— 若当前那轮还没落库（例如流式中），
 * 直接提示用户稍后再点。
 */
async function onCaptureCompare(): Promise<void> {
  const rag = compareRag.value;
  if (!rag?.id) {
    ElMessage.warning('这轮回答还没落库，等生成完成后才能建用例');
    return;
  }
  if (capturing.value) return;
  capturing.value = true;
  try {
    await evalApi.submitFeedback(rag.id, { rating: 'down', comment: '对照后发现差异，建为评测用例' });
    onFeedback(rag.id, 'down');
    ElMessage.success('已送进评测候选池，到「评测 → 候选题池」补判分关键词即可计分');
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加入候选池失败，请重试');
  } finally {
    capturing.value = false;
  }
}
</script>

<template>
  <section class="chat-view" data-testid="page-chat">
    <div v-if="loading" class="chat-view__state" data-testid="chat-loading">正在加载对话…</div>
    <div v-else-if="error" class="chat-view__state chat-view__state--error" data-testid="chat-error">
      {{ error }}
    </div>

    <template v-else>
      <MessageList
        ref="messageListRef"
        :messages="messages"
        :streaming="streaming"
        :pending-label="chat.pending.value"
        :hide-assistant-in-compare="mode === 'both'"
        @retry="retry"
        @suggest="send"
        @open-in-knowledge="onOpenInKnowledge"
        @feedback="onFeedback"
      />

      <ComparePane
        v-if="showCompare"
        :rag="compareRag"
        :direct="compareDirect"
        :rag-draft="chat.draft.value"
        :direct-draft="chat.state.value.directDraft"
        :rag-pending="chat.isStreaming.value"
        :direct-pending="chat.isStreaming.value && chat.state.value.directDraft === ''"
        :live="chat.isStreaming.value"
        @cite="onCompareCite"
        @capture="onCaptureCompare"
      />

      <RetrievalTrace v-if="traceForLast" :trace="traceForLast" />

      <SuggestionChips
        v-if="showExamples"
        :items="SEED_EXAMPLES"
        :disabled="chat.isStreaming.value || systemStatus.experimentRunning"
        @pick="send"
      />

      <ChatInput
        :mode="mode"
        :k="k"
        :disabled="clearing || systemStatus.experimentRunning"
        :streaming="chat.isStreaming.value"
        @send="send"
        @stop="chat.stop()"
        @clear="onClear"
        @update:mode="onMode"
        @update:k="onK"
      />
    </template>
  </section>
</template>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.chat-view__state {
  padding: 24px;
  color: var(--muted);
  font-size: 13px;
}

.chat-view__state--error {
  color: var(--red);
}
</style>
