package com.xiaoyi.rag.model.vo;

/**
 * 管理端用户行，对应 openapi-public.yaml#/components/schemas/AdminUserItem。
 *
 * <p><b>没有 passwordHash</b>：这是对外 VO，schema 是 {@code additionalProperties: false}，任何哈希都不许出接口。
 *
 * <p>{@code displayName} 可以是 null（V11 之前的存量行），前端按 {@code displayName ?? username} 回退显示。
 */
public record AdminUserItemVO(
        Long id,
        String username,
        String displayName,
        String role,
        boolean deleted,
        long createdAt) {}
