package com.xiaoyi.rag.common.support;

import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;

/**
 * 取当前登录用户，拿不到就失败关闭。
 *
 * <p>H2 之前各控制器用 {@code userId == null ? 1L : userId} 兜底，等价于「没登录就是 demo 用户」： 任何人删掉 Authorization
 * 头就能读写别人的资料。现在所有需要身份的路由都必须 {@code CurrentUser.require(...)}， 缺身份直接 401 / 40100，没有任何默认用户。
 *
 * <p>为什么不用 {@code @RequestAttribute(required = true)}：缺属性时 Spring 抛 {@code
 * MissingRequestAttributeException}，全局异常处理器会把它归到 50000（500），而契约要求 401/40100。
 */
public final class CurrentUser {

    private CurrentUser() {}

    /**
     * 校验并返回当前用户 id。
     *
     * @param userId 拦截器写入的 {@code xiaoyi.userId}，可能为 null
     * @return 正整数用户 id
     * @throws ApiException 缺身份或非法身份，401 / 40100
     */
    public static Long require(Long userId) {
        if (userId == null || userId <= 0) {
            throw new ApiException(
                    ErrorCode.UNAUTHENTICATED.getCode(),
                    ErrorCode.UNAUTHENTICATED.getDefaultMessage());
        }
        return userId;
    }
}
