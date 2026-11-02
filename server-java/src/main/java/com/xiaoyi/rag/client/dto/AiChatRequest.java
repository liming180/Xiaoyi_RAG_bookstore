package com.xiaoyi.rag.client.dto;

import java.util.List;

/**
 * 内部契约（/internal/v1/chat/stream）的请求体，字段名按 docs/api/openapi-internal.yaml 使用 snake_case。
 *
 * <p>Java 侧统一用 camelCase，序列化时由 Jackson 的 SNAKE_CASE 命名策略转换。
 */
public record AiChatRequest(
        String question, List<HistoryTurn> history, String mode, Integer k, List<String> acl) {

    /** 一轮历史对话。 */
    public record HistoryTurn(String role, String content) {}
}
