package com.xiaoyi.rag.common.result;

import java.time.Instant;

/**
 * 统一响应信封，对应 docs/api/envelope.schema.json。
 *
 * <pre>
 * { "code": 0, "message": "success", "data": {}, "timestamp": 1730000000 }
 * </pre>
 *
 * <p>约束：
 *
 * <ul>
 *   <li>{@code data} 字段始终存在，允许为 {@code null}（失败时固定 null）。
 *   <li>{@code timestamp} 为 Unix 秒，非毫秒，非字符串。
 *   <li>SSE 端点例外：每帧 {@code data} 是业务 JSON，不套信封。
 * </ul>
 */
public final class Result<T> {

    private int code;
    private String message;
    private T data;
    private long timestamp;

    public Result() {
        this.timestamp = Instant.now().getEpochSecond();
    }

    private Result(int code, String message, T data) {
        this.code = code;
        this.message = message;
        this.data = data;
        this.timestamp = Instant.now().getEpochSecond();
    }

    public static <T> Result<T> ok(T data) {
        return new Result<>(0, "success", data);
    }

    public static <T> Result<T> ok() {
        return new Result<>(0, "success", null);
    }

    public static <T> Result<T> fail(int code, String message) {
        return new Result<>(code, message, null);
    }

    public int getCode() {
        return code;
    }

    public void setCode(int code) {
        this.code = code;
    }

    public String getMessage() {
        return message;
    }

    public void setMessage(String message) {
        this.message = message;
    }

    public T getData() {
        return data;
    }

    public void setData(T data) {
        this.data = data;
    }

    public long getTimestamp() {
        return timestamp;
    }

    public void setTimestamp(long timestamp) {
        this.timestamp = timestamp;
    }
}
