package com.xiaoyi.rag.common.exception;

/**
 * 业务异常：携带信封中的 {@code code}，由 {@code GlobalExceptionHandler} 转成 {@code Result.fail(code, message)}
 * 并同步 HTTP 状态码。
 */
public class ApiException extends RuntimeException {

    private final int code;

    public ApiException(int code, String message) {
        super(message);
        this.code = code;
    }

    public ApiException(int code, String message, Throwable cause) {
        super(message, cause);
        this.code = code;
    }

    public int getCode() {
        return code;
    }
}
