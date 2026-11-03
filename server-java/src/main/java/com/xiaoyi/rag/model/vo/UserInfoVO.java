package com.xiaoyi.rag.model.vo;

/** 当前登录用户，对应 openapi-public.yaml#/components/schemas/UserInfo。 */
public record UserInfoVO(Long id, String username, String displayName) {}
