/**
 * API 层唯一对外出口。
 * 组件/composable 一律从 '@/api' 导入，禁止直接 import axios 或深路径导入模块。
 */
export * as authApi from './modules/auth';
export * as chatApi from './modules/chat';
export * as knowledgeApi from './modules/knowledge';
export * as evalApi from './modules/eval';

export { ApiError, getToken, setToken, TOKEN_KEY, http } from './http';
export { on, emit, clearAllListeners } from './events';
export { createSseParser, toChatEvent, streamChat, AbortStreamError } from './sse';
export { normalizeCitation, normalizeCitations, normalizeMessage, normalizeMessages } from './normalize';
