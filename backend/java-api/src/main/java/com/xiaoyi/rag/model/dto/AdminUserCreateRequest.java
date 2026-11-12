package com.xiaoyi.rag.model.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * 管理端新建用户请求。
 *
 * <p><b>为什么显式声明一个 {@code role} 字段却不用它：</b>全局 Jackson 是「忽略未知字段」配置， 如果这里不声明 {@code role}，调用方传 {@code
 * {"role":"ADMIN"}} 会被静默丢掉 —— 结果虽然是 USER（service 强制），但**契约承诺的 40001 没有发生**，属于「说好了拒却默默接受」。
 *
 * <p>三种做法里选了第三种：
 *
 * <ol>
 *   <li>全局开 {@code FAIL_ON_UNKNOWN_PROPERTIES} —— 会连带改变另外 32 条接口的入参宽容度，不是本功能的权限；
 *   <li>在 DTO 上开 {@code @JsonIgnoreProperties(ignoreUnknown = false)} —— 局部可以，但报的是 Jackson
 *       的反序列化异常，落到 40001「请求体格式不合法」，文案对调用方没有指向性；
 *   <li><b>声明字段 + service 层显式拒绝</b>（本方案）—— 报 40001 且文案直接说「不能指定角色」， 调用方一眼知道错在哪。
 * </ol>
 *
 * <p>{@code role} 只要出现（非空白）就拒绝；传 null 或不传都算「没指定」，正常创建为 USER。
 */
public record AdminUserCreateRequest(
        @NotBlank(message = "用户名不能为空") @Size(min = 1, max = 64, message = "用户名长度需在 1-64 之间")
                String username,
        @NotBlank(message = "密码不能为空") String password,
        @Size(max = 64, message = "显示名长度不能超过 64") String displayName,
        /** 仅用于识别并拒绝「试图指定角色」的请求，绝不参与落库。 */
        String role) {

    /** 便捷构造：测试与内部调用不关心 role 陷阱时用它。 */
    public AdminUserCreateRequest(String username, String password, String displayName) {
        this(username, password, displayName, null);
    }
}
