package com.xiaoyi.rag.common.enums;

import org.springframework.http.HttpStatus;

/**
 * 错误码总表，与 docs/api/error-codes.md 一一对应。
 *
 * <p>编号分段：0 成功 / 400xx 参数校验 / 401xx 未认证 / 404xx 资源不存在 / 409xx 业务冲突 / 500xx 内部 / 501xx 未实现 / 503xx
 * AI 降级。
 */
public enum ErrorCode {
    SUCCESS(0, "success", HttpStatus.OK),

    INVALID_PARAM(40001, "参数不合法", HttpStatus.BAD_REQUEST),
    INVALID_CHUNK_SIZE(40002, "片段长度需在 50-1000 之间", HttpStatus.BAD_REQUEST),
    INVALID_OVERLAP(40003, "重叠字数必须小于片段长度", HttpStatus.BAD_REQUEST),
    EMPTY_PARAM_MATRIX(40004, "参数矩阵为空", HttpStatus.BAD_REQUEST),

    UNAUTHENTICATED(40100, "登录已过期", HttpStatus.UNAUTHORIZED),
    ACCESS_DENIED(40101, "无权访问", HttpStatus.UNAUTHORIZED),
    INVALID_INTERNAL_TOKEN(40102, "内部令牌无效", HttpStatus.UNAUTHORIZED),

    DOCUMENT_NOT_FOUND(40401, "资料不存在", HttpStatus.NOT_FOUND),
    INDEX_TASK_NOT_FOUND(40402, "任务不存在", HttpStatus.NOT_FOUND),
    EVAL_RUN_NOT_FOUND(40403, "评测记录不存在", HttpStatus.NOT_FOUND),
    CANDIDATE_NOT_FOUND(40404, "候选不存在", HttpStatus.NOT_FOUND),
    EXPERIMENT_NOT_FOUND(40405, "实验不存在", HttpStatus.NOT_FOUND),
    CONVERSATION_NOT_FOUND(40406, "会话不存在", HttpStatus.NOT_FOUND),
    MESSAGE_NOT_FOUND(40407, "消息不存在", HttpStatus.NOT_FOUND),

    EXPERIMENT_BUSY(40901, "实验进行中，提问暂不可用", HttpStatus.CONFLICT),
    EXPERIMENT_ALREADY_RUNNING(40902, "已有实验在执行", HttpStatus.CONFLICT),
    INDEX_TASK_ALREADY_RUNNING(40903, "已有建库任务在执行", HttpStatus.CONFLICT),

    INTERNAL_ERROR(50000, "服务内部错误", HttpStatus.INTERNAL_SERVER_ERROR),
    MODEL_FAILED(50001, "模型调用失败", HttpStatus.INTERNAL_SERVER_ERROR),

    NOT_IMPLEMENTED(50101, "尚未实现", HttpStatus.NOT_IMPLEMENTED),

    AI_UNAVAILABLE(50301, "AI 服务不可用", HttpStatus.SERVICE_UNAVAILABLE);

    private final int code;
    private final String defaultMessage;
    private final HttpStatus httpStatus;

    ErrorCode(int code, String defaultMessage, HttpStatus httpStatus) {
        this.code = code;
        this.defaultMessage = defaultMessage;
        this.httpStatus = httpStatus;
    }

    public int getCode() {
        return code;
    }

    public String getDefaultMessage() {
        return defaultMessage;
    }

    public HttpStatus getHttpStatus() {
        return httpStatus;
    }

    /** 按 code 反查 HTTP 状态码；未登记的码统一按 500 处理。 */
    public static HttpStatus statusOf(int code) {
        for (ErrorCode item : values()) {
            if (item.code == code) {
                return item.httpStatus;
            }
        }
        if (code >= 40000 && code < 50000) {
            return HttpStatus.BAD_REQUEST;
        }
        if (code >= 50000) {
            return HttpStatus.INTERNAL_SERVER_ERROR;
        }
        return HttpStatus.OK;
    }
}
