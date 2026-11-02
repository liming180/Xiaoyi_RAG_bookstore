package com.xiaoyi.rag.common.exception;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.result.Result;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.BindException;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingPathVariableException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

/**
 * 全局异常出口：任何异常都转成统一信封，且 HTTP 状态码与 code 同步。
 *
 * <p>映射规则（手册 §5 J1 第 3 条）：
 *
 * <ul>
 *   <li>参数校验类 → {@code 40001} + HTTP 400
 *   <li>{@link ApiException} → 其自带 code + 按 {@link ErrorCode#statusOf(int)} 定状态码
 *   <li>{@link SecurityException} / AccessDenied → {@code 40101} + HTTP 401
 *   <li>其它 → {@code 50000} + HTTP 500
 * </ul>
 *
 * <p><b>为什么直接写 response 而不是返回 {@code ResponseEntity}：</b>内容协商会看请求的 {@code Accept}。`POST
 * /api/v1/chat/stream` 声明了 {@code produces=text/event-stream}，前端也按契约发 {@code Accept:
 * text/event-stream}；此时若异常处理器返回 JSON 对象，Spring 找不到可接受的表现形式，会抛 {@code
 * HttpMediaTypeNotAcceptableException}，最终落到 500 + 空响应体 —— 40001 与 40406 就全丢了。直接往 {@code
 * HttpServletResponse} 写 JSON 能绕开协商，保证**任何** Accept 下都拿到标准信封。
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    private final ObjectMapper objectMapper;

    public GlobalExceptionHandler(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    /** 业务异常：code 自带，HTTP 状态码由错误码表推导。 */
    @ExceptionHandler(ApiException.class)
    public void handleApiException(
            ApiException ex, HttpServletRequest request, HttpServletResponse response) {
        HttpStatus status = ErrorCode.statusOf(ex.getCode());
        log.debug(
                "业务异常 {} {} -> code={} status={}",
                request.getMethod(),
                request.getRequestURI(),
                ex.getCode(),
                status.value());
        write(response, status, ex.getCode(), ex.getMessage());
    }

    /**
     * @Valid 校验失败。
     */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public void handleValidation(MethodArgumentNotValidException ex, HttpServletResponse response) {
        String detail =
                ex.getBindingResult().getFieldErrors().stream()
                        .map(this::describeFieldError)
                        .collect(Collectors.joining("；"));
        badRequest(response, detail);
    }

    /** 表单绑定校验失败。 */
    @ExceptionHandler(BindException.class)
    public void handleBind(BindException ex, HttpServletResponse response) {
        String detail =
                ex.getBindingResult().getFieldErrors().stream()
                        .map(this::describeFieldError)
                        .collect(Collectors.joining("；"));
        badRequest(response, detail);
    }

    /** 路径变量类型不匹配，例如 /index/tasks/abc 而契约要求数字 id。 */
    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public void handleTypeMismatch(
            MethodArgumentTypeMismatchException ex, HttpServletResponse response) {
        badRequest(response, "参数 " + ex.getName() + " 类型不合法");
    }

    /** 必填 query 参数缺失。 */
    @ExceptionHandler(MissingServletRequestParameterException.class)
    public void handleMissingParam(
            MissingServletRequestParameterException ex, HttpServletResponse response) {
        badRequest(response, "缺少必填参数 " + ex.getParameterName());
    }

    /** 必填路径变量缺失。 */
    @ExceptionHandler(MissingPathVariableException.class)
    public void handleMissingPathVariable(
            MissingPathVariableException ex, HttpServletResponse response) {
        badRequest(response, "缺少路径变量 " + ex.getVariableName());
    }

    /** 请求体不是合法 JSON 或无法反序列化。 */
    @ExceptionHandler(HttpMessageNotReadableException.class)
    public void handleUnreadable(HttpMessageNotReadableException ex, HttpServletResponse response) {
        badRequest(response, "请求体格式不合法");
    }

    /** 权限不足。 */
    @ExceptionHandler(SecurityException.class)
    public void handleAccessDenied(SecurityException ex, HttpServletResponse response) {
        write(
                response,
                HttpStatus.UNAUTHORIZED,
                ErrorCode.ACCESS_DENIED.getCode(),
                ErrorCode.ACCESS_DENIED.getDefaultMessage());
    }

    /** 兜底：任何未预料的异常都不许漏出 Spring 默认白页。 */
    @ExceptionHandler(Exception.class)
    public void handleOthers(
            Exception ex, HttpServletRequest request, HttpServletResponse response) {
        log.error("未捕获异常 {} {}", request.getMethod(), request.getRequestURI(), ex);
        write(
                response,
                HttpStatus.INTERNAL_SERVER_ERROR,
                ErrorCode.INTERNAL_ERROR.getCode(),
                ErrorCode.INTERNAL_ERROR.getDefaultMessage());
    }

    private void badRequest(HttpServletResponse response, String detail) {
        String message =
                detail == null || detail.isEmpty()
                        ? ErrorCode.INVALID_PARAM.getDefaultMessage()
                        : detail;
        write(response, HttpStatus.BAD_REQUEST, ErrorCode.INVALID_PARAM.getCode(), message);
    }

    /**
     * 把信封直接写进响应体。
     *
     * @param response 响应
     * @param status HTTP 状态码
     * @param code 业务码
     * @param message 文案
     */
    private void write(HttpServletResponse response, HttpStatus status, int code, String message) {
        if (response.isCommitted()) {
            // 已经写出过响应头（例如 SSE 流已开始）：此时改不了状态码，只能记日志。
            log.warn("响应已提交，无法回写错误码 code={} message={}", code, message);
            return;
        }
        response.reset();
        response.setStatus(status.value());
        response.setCharacterEncoding("UTF-8");
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        try {
            objectMapper.writeValue(response.getWriter(), Result.fail(code, message));
        } catch (IOException ex) {
            log.error("回写错误信封失败 code={}", code, ex);
        }
    }

    private String describeFieldError(FieldError error) {
        return error.getField() + " " + error.getDefaultMessage();
    }
}
