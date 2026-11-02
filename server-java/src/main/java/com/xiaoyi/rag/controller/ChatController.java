package com.xiaoyi.rag.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.common.interceptor.AuthInterceptor;
import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.model.dto.ChatCommand;
import com.xiaoyi.rag.model.dto.ChatContext;
import com.xiaoyi.rag.model.dto.ChatRequest;
import com.xiaoyi.rag.model.vo.RetrievalTraceVO;
import com.xiaoyi.rag.service.ChatService;
import com.xiaoyi.rag.service.ChatStreamFrame;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import java.io.IOException;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * 问答：2 条对外接口。
 *
 * <p>operationId：chatStream（SSE）/ getMessageTrace。
 *
 * <p>{@code chatStream} 的三条硬约束（手册 §7）：
 *
 * <ol>
 *   <li>先 {@code prepare} 再建 emitter —— 校验失败要能返回 400/404 的 JSON 信封，而一旦响应头写成 {@code
 *       text/event-stream} 就回不去了；
 *   <li>每帧 {@code send} 之后 Spring 会立即 flush，不攒批（{@code SseEmitter} 的默认行为）；
 *   <li>客户端断开要停掉上游：{@code onCompletion} / {@code onTimeout} 里置取消标记，后续事件直接丢弃。
 * </ol>
 */
@RestController
@RequestMapping("/api/v1")
@Tag(name = "问答")
public class ChatController {

    private static final Logger log = LoggerFactory.getLogger(ChatController.class);

    /**
     * SSE 超时设为 0 表示不超时。
     *
     * <p>问答链路可能跑很久（Python 侧 LLM 生成 + 重排），固定超时会把长回答腰斩；真正的兜底是 Resilience4j 的 TimeLimiter（J6 接真 Python
     * 时才有意义），以及客户端自身的 AbortController。
     */
    private static final long SSE_TIMEOUT_MS = 0L;

    private final ChatService chatService;

    private final ObjectMapper objectMapper;

    public ChatController(ChatService chatService, ObjectMapper objectMapper) {
        this.chatService = chatService;
        this.objectMapper = objectMapper;
    }

    /**
     * 流式问答。
     *
     * @param request 请求体
     * @param userId 拦截器写入的当前用户
     * @return SSE 事件流
     */
    @PostMapping(value = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    @Operation(operationId = "chatStream", summary = "流式问答（text/event-stream）")
    public SseEmitter chatStream(
            @Valid @RequestBody(required = false) ChatRequest request,
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId) {
        // 所有可能失败的校验都在建 emitter 之前完成，失败时 GlobalExceptionHandler 能正常回信封。
        ChatContext context =
                chatService.prepare(
                        new ChatCommand(
                                userId == null ? 1L : userId,
                                parseId(request == null ? null : request.conversationId()),
                                request == null ? null : request.question(),
                                request == null ? null : request.mode(),
                                request == null ? null : request.k()));

        SseEmitter emitter = new SseEmitter(SSE_TIMEOUT_MS);
        AtomicBoolean closed = new AtomicBoolean(false);

        emitter.onCompletion(
                () -> {
                    if (closed.compareAndSet(false, true)) {
                        log.debug("SSE 完成 conversationId={}", context.conversationId());
                    }
                });
        emitter.onTimeout(
                () -> {
                    closed.set(true);
                    log.warn("SSE 超时 conversationId={}", context.conversationId());
                    emitter.complete();
                });
        emitter.onError(
                ex -> {
                    closed.set(true);
                    log.warn(
                            "SSE 连接异常 conversationId={}：{}",
                            context.conversationId(),
                            ex.getMessage());
                });

        chatService.stream(
                context,
                new ChatService.EventSink() {
                    @Override
                    public void emit(ChatStreamFrame frame) {
                        if (closed.get()) {
                            // 客户端已断开：丢弃后续事件，避免 IllegalStateException 刷日志。
                            return;
                        }
                        try {
                            emitter.send(
                                    SseEmitter.event()
                                            .name(frame.event())
                                            .data(
                                                    objectMapper.writeValueAsString(frame.data()),
                                                    MediaType.TEXT_PLAIN));
                        } catch (IOException | IllegalStateException ex) {
                            closed.set(true);
                            log.debug("SSE 推送失败，视为客户端断开：{}", ex.getMessage());
                        }
                    }

                    @Override
                    public void complete() {
                        if (closed.compareAndSet(false, true)) {
                            emitter.complete();
                        }
                    }

                    @Override
                    public void fail(Throwable error) {
                        if (closed.compareAndSet(false, true)) {
                            emitter.completeWithError(error);
                        }
                    }
                });

        return emitter;
    }

    /**
     * 某条助手消息的检索过程。
     *
     * @param id 消息 id（字符串，契约里是 EntityId 双形状）
     * @param userId 当前用户
     * @return 轨迹；无轨迹时 data 为 null（不报错）
     */
    @GetMapping("/messages/{id}/trace")
    @Operation(operationId = "getMessageTrace", summary = "检索轨迹；无轨迹时 data=null")
    public Result<RetrievalTraceVO> trace(
            @PathVariable String id,
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId) {
        return Result.ok(chatService.trace(userId == null ? 1L : userId, parseMessageId(id)));
    }

    /**
     * 解析会话 id。契约里是 {@code EntityId}（字符串或整数双形状），非法值返回 null 表示「新建会话」， 而不是抛 500。
     *
     * @param raw 原始字符串
     * @return 数字 id 或 null
     */
    private Long parseId(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        try {
            return Long.valueOf(raw.trim());
        } catch (NumberFormatException ex) {
            // 前端 mock 的 id 形如 c-2001，落到真实后端时找不到对应会话，按 40406 处理更准确；
            // 这里用 -1 而不是 null，null 会被当成「新建会话」而静默多建一条。
            return -1L;
        }
    }

    /**
     * 解析消息 id。非法值统一走 40407，不让 {@code NumberFormatException} 变成 500。
     *
     * @param raw 原始字符串
     * @return 数字 id，非法时返回 -1
     */
    private Long parseMessageId(String raw) {
        try {
            return Long.valueOf(raw == null ? "" : raw.trim());
        } catch (NumberFormatException ex) {
            throw new ApiException(
                    ErrorCode.MESSAGE_NOT_FOUND.getCode(),
                    ErrorCode.MESSAGE_NOT_FOUND.getDefaultMessage());
        }
    }
}
