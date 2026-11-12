package com.xiaoyi.rag.model.vo;

/** 演示模式登录结果，对应 openapi-public.yaml#/components/schemas/LoginResult。 */
public record LoginResultVO(String token, long expiresIn, UserInfoVO user) {}
