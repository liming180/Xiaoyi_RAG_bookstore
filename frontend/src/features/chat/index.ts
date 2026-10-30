/**
 * chat 特性的唯一对外出口。
 * 外部（路由 / 其他特性）只允许从这里导入，禁止深层引用内部文件。
 */
export { default as MessageList } from './components/MessageList.vue';
export { default as MessageBubble } from './components/MessageBubble.vue';
export { default as AnswerBody } from './components/AnswerBody.vue';
export { default as InlineRenderer } from './components/InlineRenderer.vue';
export { default as SourceRef } from './components/SourceRef.vue';
export { default as CitationCard } from './components/CitationCard.vue';
export { useConversation } from './composables/useConversation';
