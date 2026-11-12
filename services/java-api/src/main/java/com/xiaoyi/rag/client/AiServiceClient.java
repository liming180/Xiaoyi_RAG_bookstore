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
 *
 * <p><b>H2 起每个方法都以 {@code userId} 开头</b>：Python 侧所有内部端点都按 {@code X-User-Id} 头做归属校验，
 * 检索、入库、状态、文档查询都只返回该用户自己的数据。 少传一次 userId 就等于让两个用户共用一份知识库，所以这个参数没有默认值、没有重载。
 *
 * <p><b>H3 起 {@link #chatStream} 返回可取消句柄</b>：浏览器断开 SSE 后必须真正停掉上游， 否则 Python 仍在生成、Java 仍在解析，白白占用连接与
 * token。
 */
public interface AiServiceClient {

    /**
     * 流式问答。实现方按顺序推送 status → retrieval → token… → done（或 error）。
     *
     * @param userId 当前用户，透传成 {@code X-User-Id}
     * @param request 问题、历史、模式、top-k
     * @param listener 事件回调，由 Controller 直接写进 SseEmitter
     * @return 可取消句柄；调用方在客户端断开时 {@link StreamHandle#cancel()} 停止上游
     */
    StreamHandle chatStream(Long userId, AiChatRequest request, StreamListener listener);

    /**
     * 触发解析入库，立即返回 Python 侧 task_id。
     *
     * @param userId 当前用户
     * @param request 待入库的资料、分片参数、幂等键与代际
     * @return Python 侧任务标识与文档数
     */
    AiParseResult parseDocuments(Long userId, AiParseRequest request);

    /**
     * 查一次入库任务进度。
     *
     * @param userId 当前用户；跨用户的任务在 Python 侧按不存在处理
     * @param taskId Python 侧任务标识
     * @return 当前进度；任务已成功时可能带片段清单
     */
    AiIngestTask getIngestTask(Long userId, String taskId);

    /**
     * 查 Python 侧索引状态。
     *
     * @param userId 当前用户
     * @return manifest；Python 不可达时由调用方合成 {@code unavailable}，本方法直接抛异常
     */
    AiIndexManifest getIndexManifest(Long userId);

    /** J6 纯检索调用，供片段浏览与追踪扩展使用。 */
    default JsonNode retrieve(Long userId, Map<String, Object> request) {
        throw new UnsupportedOperationException("retrieve is available in J6 real client");
    }

    /** J6 批量评测调用。 */
    default JsonNode evalBatch(Long userId, Map<String, Object> request) {
        throw new UnsupportedOperationException("evalBatch is available in J6 real client");
    }

    /** J6 单资料状态查询。 */
    default JsonNode getDocumentStatus(Long userId, String documentId) {
        throw new UnsupportedOperationException("getDocumentStatus is available in J6 real client");
    }

    /** 健康检查。刻意不带 userId：这是进程级探活，不属于任何用户。 */
    default JsonNode health() {
        throw new UnsupportedOperationException("health is available in J6 real client");
    }

    /** 事件回调。 */
    interface StreamListener {
        void onEvent(AiStreamEvent event);

        void onError(Throwable error);
    }

    /** 一次流式调用的句柄，唯一职责是让调用方在客户端断开后停止上游。 */
    interface StreamHandle {

        /** 空实现，给不支持取消的客户端用。 */
        StreamHandle NOOP = () -> {};

        /** 停止上游；重复调用必须无害。 */
        void cancel();
    }
}
