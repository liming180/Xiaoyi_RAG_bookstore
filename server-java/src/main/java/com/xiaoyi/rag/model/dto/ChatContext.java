package com.xiaoyi.rag.model.dto;

import com.xiaoyi.rag.client.dto.AiChatRequest.HistoryTurn;
import java.util.List;

/**
 * 一次问答的编排上下文：{@link ChatService#prepare} 校验并落定所有入参后的产物。
 *
 * <p>拆成「prepare → stream」两步是为了让参数校验失败能走正常信封（HTTP 400 + JSON）， 而不是先建好 {@code SseEmitter} 再抛异常 ——
 * 那样响应头已经写成 {@code text/event-stream}， 错误体就发不出去了。
 *
 * @param userId 会话归属
 * @param conversationId 会话 id（入参为 null 时自动新建）
 * @param question 已 trim 的问题
 * @param mode 归一化后的模式 rag / direct / both
 * @param k 归一化后的召回条数
 * @param history 最近 N 轮对话（不含本次提问）
 */
public record ChatContext(
        Long userId,
        Long conversationId,
        String question,
        String mode,
        int k,
        List<HistoryTurn> history) {}
