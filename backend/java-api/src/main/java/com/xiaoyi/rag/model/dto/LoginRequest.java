package com.xiaoyi.rag.model.dto;

import jakarta.validation.constraints.NotBlank;

/**
 * 登录请求，对应 openapi-public.yaml#/components/schemas/LoginRequest。
 *
 * <p>两个字段都用 {@link NotBlank}：空口令属于「参数不合法」（400/40001），不该被当成一次失败的凭据校验 （401/40100）。服务层仍然保留一次空口令拒绝，作为绕过
 * Web 校验时的兜底。
 */
public record LoginRequest(
        @NotBlank(message = "用户名不能为空") String username,
        @NotBlank(message = "密码不能为空") String password) {}
