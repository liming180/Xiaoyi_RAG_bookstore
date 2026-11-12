package com.xiaoyi.rag.model.dto;

/**
 * 一次流式问答的编排入参（对外 {@link ChatRequest} 的内部形态）。
 *
 * <p>多带两个字段是有原因的：
 *
 * <ul>
 *   <li>{@code userId} —— 落库要写会话归属，也要校验会话是不是当前用户的；
 *   <li>{@code conversationId} 用 {@code Long} —— 对外契约里它是 {@code EntityId}（字符串或整数双形状）， 到 Service
 *       层已经过 {@code parseId}，非法值不会进来。
 * </ul>
 *
 * @param userId 当前用户 id
 * @param conversationId 会话 id；null 表示「新会话」，由 Service 自动建一个
 * @param question 用户问题
 * @param mode 回答模式 rag / direct / both，null 按 rag
 * @param k 召回条数，null 按 3
 */
public record ChatCommand(
        Long userId, Long conversationId, String question, String mode, Integer k) {}
