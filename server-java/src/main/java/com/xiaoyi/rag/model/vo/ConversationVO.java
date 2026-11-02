package com.xiaoyi.rag.model.vo;

/**
 * 会话视图，对应契约 {@code components.schemas.Conversation}。
 *
 * <p>契约 required：{@code [id, title, createdAt, updatedAt, messageCount]}， {@code
 * additionalProperties: false} —— 多一个字段都会让契约校验失败，故这里不塞任何额外信息。
 *
 * <p>{@code id} 用 {@code String}：契约 {@code EntityId} 是 {@code oneOf[string, integer]}，
 * 统一出字符串对前端更稳（{@code frontend/src/api/modules/chat.ts} 两种都吃）。
 *
 * @param id 会话 id
 * @param title 标题
 * @param createdAt 创建时间（Unix 秒）
 * @param updatedAt 更新时间（Unix 秒），列表按它倒序
 * @param messageCount 未删除消息数
 */
public record ConversationVO(
        String id, String title, Long createdAt, Long updatedAt, Integer messageCount) {}
