package com.xiaoyi.rag.model.vo;

/**
 * 管理端审计行，对应 openapi-public.yaml#/components/schemas/AdminAuditItem。
 *
 * <p>{@code detailJson} 原样返回字符串（不解析成对象）：审计详情是「写入时那一刻的快照」， 用 {@code String} 传输保证历史记录的字节不被当前 schema
 * 重新解释——前端只做展示与 pretty-print。
 *
 * <p>{@code operatorName} 是操作者的 username（可能为 null：账号已被硬删或历史行的 userId 指向不存在的用户）。 为什么在服务端 join
 * 出来而不是让前端再查一次：前端拿到的 userId 在用户被软删后依然存在， 但显示「谁做的」必须用 username，否则审计页全是数字。
 */
public record AdminAuditItemVO(
        Long id,
        Long operatorId,
        String operatorName,
        String action,
        String target,
        String detailJson,
        long createdAt) {}
