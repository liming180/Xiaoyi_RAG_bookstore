package com.xiaoyi.rag.model.dto;

import jakarta.validation.constraints.NotBlank;

/** 登录请求，对应 openapi-public.yaml#/components/schemas/LoginRequest。 */
public record LoginRequest(@NotBlank(message = "用户名不能为空") String username, String password) {}
