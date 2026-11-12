package com.xiaoyi.rag.model.vo;

/**
 * 当前登录用户，对应 openapi-public.yaml#/components/schemas/UserInfo。
 *
 * <p>{@code role} 是 V11 之后新增的字段（{@code ADMIN} / {@code USER}）：前端靠它决定登录后落管理端还是用户端， 路由守卫 {@code
 * adminGuard} 也读这个值。取值为 {@code ADMIN} 时说明这是管理端唯一账号。
 */
public record UserInfoVO(Long id, String username, String displayName, String role) {}
