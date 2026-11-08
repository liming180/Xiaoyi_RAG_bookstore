import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useChat } from '@/features/chat/composables/useChat';
import { useConversation } from '@/features/chat/composables/useConversation';
import type { Message } from '@/types/api';
import { getState, resetState } from '@/mocks/state';
import { chatApi } from '@/api';

/**
 * 发送链路集成测试：真走 MSW 的 SSE 流，断言状态机最终结果与落库。
 */
describe('useChat 发送链路（F04）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('发问后产出完整回答、引用与追问建议，并落库', async () => {
    const persisted: Message[] = [];
    const chat = useChat({
      conversationId: () => 'c-demo',
      onPersist: (m) => persisted.push(m),
    });

    const ok = await chat.send('普通图书最多同时借阅几本借多久？', 'rag', 3);

    expect(ok).toBe(true);
    expect(chat.state.value.phase).toBe('done');
    // 判分关键词是逐字 includes 匹配（4本/21天），答案里不能写成「4 本」
    expect(chat.draft.value).toContain('4本');
    expect(chat.draft.value).toContain('21天');
    expect(chat.citations.value.length).toBeGreaterThan(0);
    expect(chat.state.value.suggestions.length).toBeGreaterThan(0);
    expect(chat.state.value.elapsedMs).toBe(2100);

    expect(persisted).toHaveLength(1);
    expect(persisted[0]!.role).toBe('assistant');
    expect(persisted[0]!.content).toContain('21天');
    expect(persisted[0]!.citations.length).toBeGreaterThan(0);
  });

  it('发送中 streamingMessage 提供增量正文（双加载态）', async () => {
    const chat = useChat({ conversationId: () => 'c-demo' });
    const task = chat.send('读书会什么时候举行？', 'rag', 3);

    // 流刚开始：阶段文案已在（status 事件先到）
    await new Promise((r) => setTimeout(r, 20));
    expect(chat.isStreaming.value).toBe(true);
    expect(chat.pending.value).not.toBe('');

    // 等第一批 token 到达（MSW 每 2ms 一帧）
    let waited = 0;
    while (waited < 2000 && (chat.streamingMessage.value?.content.length ?? 0) === 0) {
      await new Promise((r) => setTimeout(r, 10));
      waited += 10;
      if (!chat.isStreaming.value) break;
    }
    // 若流已结束（jsdom 下 MSW 可能整块送达），至少验证落库后 streaming 归零
    if (chat.isStreaming.value) {
      expect(chat.streamingMessage.value?.content.length ?? 0).toBeGreaterThan(0);
    }

    await task;
    expect(chat.streamingMessage.value).toBeNull();
    expect(chat.draft.value.length).toBeGreaterThan(0);
  });

  it('direct 模式不带引用', async () => {
    const chat = useChat({ conversationId: () => 'c-demo' });
    await chat.send('参加读书会要交多少费用？', 'direct', 3);
    expect(chat.state.value.phase).toBe('done');
    expect(chat.citations.value).toHaveLength(0);
  });

  it('both 模式带回 direct 侧正文', async () => {
    const chat = useChat({ conversationId: () => 'c-demo' });
    await chat.send('读书会什么时候举行？', 'both', 3);
    expect(chat.state.value.phase).toBe('done');
    expect(chat.state.value.directDraft.length).toBeGreaterThan(0);
    expect(chat.state.value.directMessageId).toBeTruthy();
  });

  it('空问题或缺少会话时不发送', async () => {
    const chat = useChat({ conversationId: () => 'c-demo' });
    expect(await chat.send('   ', 'rag', 3)).toBe(false);

    const noConv = useChat({ conversationId: () => null });
    expect(await noConv.send('问题', 'rag', 3)).toBe(false);
  });

  it('重复发送被拒绝（sending 期间）', async () => {
    const chat = useChat({ conversationId: () => 'c-demo' });
    const first = chat.send('读书会什么时候举行？', 'rag', 3);
    const second = await chat.send('第二个问题', 'rag', 3);
    expect(second).toBe(false);
    await first;
  });

  it('中断保留已生成内容且不进错误态', async () => {
    const chat = useChat({ conversationId: () => 'c-demo' });
    const task = chat.send('普通图书最多同时借阅几本借多久？', 'rag', 3);
    await new Promise((r) => setTimeout(r, 30));
    chat.stop();
    await task;
    expect(chat.state.value.phase).toBe('done');
    expect(chat.state.value.error).toBeNull();
    expect(chat.sending.value).toBe(false);
  });

  it('后端返回错误码时进入错误态', async () => {
    // 用实验运行中的 409 分支触发非 2xx
    const st = getState();
    st.experimentRunning = true;
    const chat = useChat({ conversationId: () => 'c-demo' });
    const ok = await chat.send('读书会什么时候举行？', 'rag', 3);
    expect(ok).toBe(false);
    expect(chat.state.value.phase).toBe('error');
    expect(chat.state.value.error?.message).toBeTruthy();
    st.experimentRunning = false;
  });
});

describe('useConversation 装载（F04）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('加载会话消息并算出最近提问与引用汇总', async () => {
    // 先发一轮，让 mock 里有真实消息
    await chatApi.streamAnswer({
      conversationId: 'c-demo',
      question: '普通图书最多同时借阅几本借多久？',
      mode: 'rag',
      k: 3,
    }).next();

    const conv = useConversation(() => 'c-demo');
    await conv.load();

    expect(conv.messages.value.length).toBeGreaterThan(0);
    expect(conv.lastQuestion.value).toContain('普通图书');
    expect(conv.allCitations.value.length).toBeGreaterThan(0);
    expect(conv.isEmpty.value).toBe(false);
  });

  it('没有会话时清空消息', async () => {
    const conv = useConversation(() => null);
    await conv.load();
    expect(conv.messages.value).toHaveLength(0);
    expect(conv.isEmpty.value).toBe(true);
  });

  it('N2：刷新/切回会话后追问 chips 仍在（落库的那一半）', async () => {
    // 先走一轮 SSE，让服务端 mock 把 assistant 消息（含 suggestions）写进 state
    const chat = useChat({ conversationId: () => 'c-demo' });
    await chat.send('普通图书最多同时借阅几本借多久？', 'rag', 3);
    const streamed = chat.state.value.suggestions;
    expect(streamed.length).toBeGreaterThan(0);

    // 模拟刷新：重新装载（丢掉流式状态，只能从接口拉历史）
    const conv = useConversation(() => 'c-demo');
    await conv.load();

    const assistant = conv.messages.value.filter((m) => m.role === 'assistant');
    expect(assistant.length).toBeGreaterThan(0);
    // 关键：`done.suggestions` 只覆盖「刚刚生成完那一刻」，能回放才说明真的落库了
    expect(assistant[assistant.length - 1]!.suggestions).toEqual(streamed);
  });
});
