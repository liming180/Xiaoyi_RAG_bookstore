package com.xiaoyi.rag.client;

import com.fasterxml.jackson.databind.JsonNode;
import com.xiaoyi.rag.client.dto.AiChatRequest;
import com.xiaoyi.rag.client.dto.AiIndexManifest;
import com.xiaoyi.rag.client.dto.AiIngestTask;
import com.xiaoyi.rag.client.dto.AiParseRequest;
import com.xiaoyi.rag.client.dto.AiParseResult;
import com.xiaoyi.rag.client.dto.AiStreamEvent;
import java.util.Map;

/**
 * 对 Python AI 服务的出口。
 *
 * <p>J1/J3 只有 {@link MockAiClient} 实现；J6 换成真实 HTTP 客户端， 接口签名保持不变，Controller / Service 不用改。
 *
 * <p>J4 新增三个入库相关方法。它们的失败语义都是「抛运行时异常」，由调用方决定降级方式： 建库触发失败 → 任务置 FAILED；轮询失败 → 计数重试；状态查询失败 → 合成 {@code
 * unavailable}。
 */
public interface AiServiceClient {

    /**
     * 流式问答。实现方按顺序推送 status → retrieval → token… → done（或 error）。
     *
     * @param request 问题、历史、模式、top-k
     * @param listener 事件回调，由 Controller 直接写进 SseEmitter
     */
    void chatStream(AiChatRequest request, StreamListener listener);

    /**
     * 触发解析入库，立即返回 Python 侧 task_id。
     *
     * @param request 待入库的资料与分片参数
     * @return Python 侧任务标识与文档数
     */
    AiParseResult parseDocuments(AiParseRequest request);

    /**
     * 查一次入库任务进度。
     *
     * @param taskId Python 侧任务标识
     * @return 当前进度；任务已成功时可能带片段清单
     */
    AiIngestTask getIngestTask(String taskId);

    /**
     * 查 Python 侧索引状态。
     *
     * @return manifest；Python 不可达时由调用方合成 {@code unavailable}，本方法直接抛异常
     */
    AiIndexManifest getIndexManifest();

    /** J6 纯检索调用，供片段浏览与追踪扩展使用。 */
    default JsonNode retrieve(Map<String, Object> request) {
        throw new UnsupportedOperationException("retrieve is available in J6 real client");
    }

    /** J6 批量评测调用。 */
    default JsonNode evalBatch(Map<String, Object> request) {
        throw new UnsupportedOperationException("evalBatch is available in J6 real client");
    }

    /** J6 单资料状态查询。 */
    default JsonNode getDocumentStatus(String documentId) {
        throw new UnsupportedOperationException("getDocumentStatus is available in J6 real client");
    }

    /** J6 AI 健康检查。 */
    default JsonNode health() {
        throw new UnsupportedOperationException("health is available in J6 real client");
    }

    /** 事件回调。 */
    interface StreamListener {
        void onEvent(AiStreamEvent event);

        void onError(Throwable error);
    }
}
