package com.xiaoyi.rag.service;

import com.xiaoyi.rag.model.dto.ChatCommand;
import com.xiaoyi.rag.model.dto.ChatContext;
import com.xiaoyi.rag.model.vo.RetrievalTraceVO;

/**
 * 问答编排：校验入参 → 取历史 → 透传事件 → 异步落库。
 *
 * <p>为什么拆成 {@link #prepare} 与 {@link #stream} 两步：{@code SseEmitter} 一旦作为返回值交给 Spring， 响应头就锁成 {@code
 * text/event-stream}，之后抛异常发不出 JSON 信封。所有可能失败的校验都必须 在拿到 emitter 之前完成，失败时让 {@code
 * GlobalExceptionHandler} 正常返回 400 / 404 信封。
 */
public interface ChatService {

    /**
     * 校验并归一化一次问答请求，必要时自动建会话。
     *
     * @param command 原始入参
     * @return 编排上下文
     * @throws com.xiaoyi.rag.common.exception.ApiException 参数非法（40001）或会话不存在（40406）
     */
    ChatContext prepare(ChatCommand command);

    /**
     * 执行一次流式问答，事件逐条推给 {@code sink}。
     *
     * <p>本方法立即返回，事件在 AI 客户端的调度线程上产生。落库在独立线程池执行，不占用流线程。
     *
     * @param context 编排上下文
     * @param sink 事件出口
     */
    void stream(ChatContext context, EventSink sink);

    /**
     * 读某条消息的检索轨迹。
     *
     * @param userId 当前用户，用于校验归属
     * @param messageId 消息 id
     * @return 轨迹；消息存在但没有检索过程时返回 null（契约要求 {@code data: null} 而不是报错）
     * @throws com.xiaoyi.rag.common.exception.ApiException 消息不存在（40407）
     */
    RetrievalTraceVO trace(Long userId, Long messageId);

    /** 事件出口，Controller 用 {@code SseEmitter} 实现。 */
    interface EventSink {

        /**
         * 推一条事件。
         *
         * @param frame 已改写成对外契约形状的帧
         */
        void emit(ChatStreamFrame frame);

        /** 正常结束流。 */
        void complete();

        /**
         * 异常结束流（仅用于客户端已断开等不可恢复场景；业务失败走降级 done）。
         *
         * @param error 异常
         */
        void fail(Throwable error);
    }
}
