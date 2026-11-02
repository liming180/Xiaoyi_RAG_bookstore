package com.xiaoyi.rag.client.dto;

import java.util.List;
import java.util.Map;

/**
 * 内部流式事件的统一载体。Python 侧每个 SSE 帧的 {@code data} 反序列化成它。
 *
 * <p>手册 §7 要求「未知事件一律透传（不抛错），保证 Python 加字段不炸 Java」。固定 record 会丢掉 未知事件的字段，所以多带一个 {@link
 * #raw()}：Python 原样的 data 映射。已知事件用结构化字段（类型安全、 转换点集中），未知事件用 {@code raw} 原样转发。
 *
 * @param event 事件名：status / retrieval / token / done / error，或 Python 未来新增的任意名
 * @param stage 仅 status 事件有值：rewriting / retrieving / reranking / generating
 * @param citations 仅 retrieval 事件有值
 * @param content 仅 token 事件有值
 * @param messageId 仅 done 事件有值
 * @param usage 仅 done 事件有值
 * @param elapsedMs 仅 done 事件有值
 * @param degraded 仅 done 事件有值
 * @param suggestions 仅 done 事件有值
 * @param directMessageId 仅 done 事件有值（mode=both 时）
 * @param directContent 仅 done 事件有值（mode=both 时）
 * @param code 仅 error 事件有值
 * @param message 仅 error 事件有值
 * @param fallback 仅 error 事件有值
 * @param raw Python 帧 data 的原始映射，未知事件靠它透传
 */
public record AiStreamEvent(
        String event,
        String stage,
        List<AiCitation> citations,
        String content,
        String messageId,
        Map<String, Object> usage,
        Long elapsedMs,
        Boolean degraded,
        List<String> suggestions,
        String directMessageId,
        String directContent,
        Integer code,
        String message,
        String fallback,
        Map<String, Object> raw) {

    /** status 事件。 */
    public static AiStreamEvent status(String stage) {
        return new AiStreamEvent(
                "status", stage, null, null, null, null, null, null, null, null, null, null, null,
                null, null);
    }

    /** retrieval 事件。 */
    public static AiStreamEvent retrieval(List<AiCitation> citations) {
        return new AiStreamEvent(
                "retrieval",
                null,
                citations,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null);
    }

    /** token 事件。 */
    public static AiStreamEvent token(String content) {
        return new AiStreamEvent(
                "token", null, null, content, null, null, null, null, null, null, null, null, null,
                null, null);
    }

    /** done 事件。 */
    public static AiStreamEvent done(
            String messageId,
            Map<String, Object> usage,
            long elapsedMs,
            boolean degraded,
            List<String> suggestions,
            String directMessageId,
            String directContent) {
        return new AiStreamEvent(
                "done",
                null,
                null,
                null,
                messageId,
                usage,
                elapsedMs,
                degraded,
                suggestions,
                directMessageId,
                directContent,
                null,
                null,
                null,
                null);
    }

    /** error 事件。 */
    public static AiStreamEvent error(int code, String message, String fallback) {
        return new AiStreamEvent(
                "error", null, null, null, null, null, null, null, null, null, null, code, message,
                fallback, null);
    }

    /**
     * 未知事件：只有事件名与原始 data。
     *
     * @param event 事件名
     * @param raw 原始 data 映射
     * @return 透传用的事件
     */
    public static AiStreamEvent unknown(String event, Map<String, Object> raw) {
        return new AiStreamEvent(
                event, null, null, null, null, null, null, null, null, null, null, null, null, null,
                raw);
    }
}
