package com.xiaoyi.rag.client;

import com.xiaoyi.rag.client.dto.AiChatRequest;
import com.xiaoyi.rag.client.dto.AiStreamEvent;

/**
 * 对 Python AI 服务的出口。
 *
 * <p>J1 只有 {@link MockAiClient} 实现；J6 换成真实 HTTP 客户端， 接口签名保持不变，Controller / Service 不用改。
 */
public interface AiServiceClient {

    /**
     * 流式问答。实现方按顺序推送 status → retrieval → token… → done（或 error）。
     *
     * @param request 问题、历史、模式、top-k
     * @param listener 事件回调，由 Controller 直接写进 SseEmitter
     */
    void chatStream(AiChatRequest request, StreamListener listener);

    /** 事件回调。 */
    interface StreamListener {
        void onEvent(AiStreamEvent event);

        void onError(Throwable error);
    }
}
