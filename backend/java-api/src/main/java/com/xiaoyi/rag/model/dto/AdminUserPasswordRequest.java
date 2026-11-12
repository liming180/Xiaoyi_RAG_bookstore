package com.xiaoyi.rag.model.dto;

import jakarta.validation.constraints.NotBlank;

/**
 * 管理端重置密码请求。
 *
 * <p>只有新密码一个字段：不要求旧密码（管理员重置他人密码的场景本来也不知道旧密码）；不做二次确认字段 —— 二次输入是前端表单的事，服务端多收一个 {@code
 * confirmPassword} 只会变成永远没人校验的死字段。
 */
public record AdminUserPasswordRequest(@NotBlank(message = "密码不能为空") String newPassword) {}
