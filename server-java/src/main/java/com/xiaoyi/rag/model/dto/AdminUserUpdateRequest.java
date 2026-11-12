package com.xiaoyi.rag.model.dto;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

/**
 * 管理端编辑用户请求：只改显示名。
 *
 * <p>显示名允许空串（表示清空 → 存 NULL，列表回退显示 username），所以字段用 {@link NotNull} 而不是 {@link
 * jakarta.validation.constraints.NotBlank}：调用方必须显式给出这个字段，但可以给空串。
 *
 * <p>改密码走独立端点 {@code PUT /admin/users/{id}/password}，便于分别留审计痕迹。
 */
public record AdminUserUpdateRequest(
        @NotNull(message = "显示名不能为空") @Size(max = 64, message = "显示名长度不能超过 64")
                String displayName) {}
