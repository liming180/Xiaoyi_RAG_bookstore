import type { ChatStreamEvent, Citation, RetrievalTrace } from '@/types/api';

/**
 * 对话流状态机（纯函数，可单测）
 *
 * 为什么要单独抽出来：SSE 的真实事件序列非常不规整 ——
 * 未知事件、缺字段、error 中途插入、degraded 与正常完成并存。
 * 把「事件 → 状态」做成纯 reducer，测试可以逐事件断言，
 * 组件只负责把状态渲染出来。
 */

export type ChatPhase = 'idle' | 'streaming' | 'done' | 'error';

export interface ChatMachineState {
  phase: ChatPhase;
  /** 最近一次 status 事件的阶段（驱动双加载态文案） */
  stage: 'rewriting' | 'retrieving' | 'reranking' | 'generating' | null;
  /** 已累积的流式正文 */
  draft: string;
  citations: Citation[];
  /** both 模式下的 direct 侧正文 */
  directDraft: string;
  /** done 事件带来的落库消息 id */
  messageId: string | null;
  directMessageId: string | null;
  elapsedMs: number | null;
  degraded: boolean;
  suggestions: string[];
  trace: RetrievalTrace | null;
  error: { code: number; message: string; fallback?: string } | null;
  /** 未知事件计数（排查用，不参与渲染决策） */
  unknownEvents: number;
}

export function initialState(): ChatMachineState {
  return {
    phase: 'idle',
    stage: null,
    draft: '',
    citations: [],
    directDraft: '',
    messageId: null,
    directMessageId: null,
    elapsedMs: null,
    degraded: false,
    suggestions: [],
    trace: null,
    error: null,
    unknownEvents: 0,
  };
}

/** 阶段文案（F04 双加载态） */
export const STAGE_TEXT: Record<string, string> = {
  rewriting: '正在理解问题…',
  retrieving: '正在检索资料…',
  reranking: '正在重排结果…',
  generating: '正在回答…',
};

/** 当前应显示的等待文案；idle/done 时为空 */
export function pendingLabel(state: ChatMachineState): string {
  if (state.phase !== 'streaming') return '';
  if (!state.stage) return '正在回答…';
  return STAGE_TEXT[state.stage] ?? '正在回答…';
}

/** 是否已经出现可见正文（决定要不要显示骨架占位） */
export function hasDraft(state: ChatMachineState): boolean {
  return state.draft.length > 0;
}

/**
 * 单事件归约。
 *
 * 关键约定：
 *  - 未知事件 identity 透传（只累加计数，绝不抛错、不中断流）
 *  - error 事件把 phase 置 error，但保留已有 draft（用户能看到已经生成的部分）
 *  - done 事件之后再来 token 一律忽略（后端偶发的尾部帧）
 */
export function reduce(state: ChatMachineState, event: ChatStreamEvent): ChatMachineState {
  switch (event.event) {
    case 'status': {
      const stage = (event.data as { stage?: string })?.stage;
      const allowed = ['rewriting', 'retrieving', 'reranking', 'generating'];
      return {
        ...state,
        phase: 'streaming',
        stage: stage && allowed.includes(stage) ? (stage as ChatMachineState['stage']) : state.stage,
      };
    }

    case 'retrieval': {
      const list = (event.data as { citations?: unknown })?.citations;
      if (!Array.isArray(list)) return { ...state, phase: 'streaming' };
      return { ...state, phase: 'streaming', citations: list as Citation[] };
    }

    case 'token': {
      if (state.phase === 'done') return state;
      const content = (event.data as { content?: unknown })?.content;
      if (typeof content !== 'string') return { ...state, phase: 'streaming' };
      return { ...state, phase: 'streaming', draft: state.draft + content };
    }

    case 'done': {
      const d = event.data as {
        messageId?: unknown;
        elapsedMs?: unknown;
        degraded?: unknown;
        suggestions?: unknown;
        directMessageId?: unknown;
        directContent?: unknown;
      };
      const suggestions = Array.isArray(d.suggestions)
        ? d.suggestions.filter((s): s is string => typeof s === 'string').slice(0, 3)
        : [];
      return {
        ...state,
        phase: 'done',
        stage: null,
        messageId: d.messageId !== undefined && d.messageId !== null ? String(d.messageId) : null,
        directMessageId:
          d.directMessageId !== undefined && d.directMessageId !== null
            ? String(d.directMessageId)
            : null,
        elapsedMs: typeof d.elapsedMs === 'number' ? d.elapsedMs : null,
        degraded: d.degraded === true,
        suggestions,
        directDraft: typeof d.directContent === 'string' ? d.directContent : state.directDraft,
      };
    }

    case 'error': {
      const d = event.data as { code?: unknown; message?: unknown; fallback?: unknown };
      return {
        ...state,
        phase: 'error',
        stage: null,
        error: {
          code: typeof d.code === 'number' ? d.code : 50000,
          message: typeof d.message === 'string' ? d.message : '生成失败，请重试',
          fallback: typeof d.fallback === 'string' ? d.fallback : undefined,
        },
      };
    }

    default:
      // 未知事件：不改变业务状态
      return { ...state, unknownEvents: state.unknownEvents + 1 };
  }
}

export function reduceAll(
  events: ChatStreamEvent[],
  from: ChatMachineState = initialState(),
): ChatMachineState {
  return events.reduce(reduce, from);
}

/** 网络层异常也走同一个错误态，保证 UI 只有一种错误渲染路径 */
export function failWith(state: ChatMachineState, message: string, code = 0): ChatMachineState {
  return { ...state, phase: 'error', stage: null, error: { code, message } };
}

/** 用户主动停止：保留已生成内容，不进错误态 */
export function abort(state: ChatMachineState): ChatMachineState {
  return { ...state, phase: 'done', stage: null };
}
