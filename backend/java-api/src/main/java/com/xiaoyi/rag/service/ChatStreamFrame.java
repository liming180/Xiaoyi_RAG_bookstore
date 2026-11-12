package com.xiaoyi.rag.service;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.xiaoyi.rag.model.vo.CitationVO;
import java.util.List;
import java.util.Map;

/**
 * 一帧对外 SSE 事件：事件名 + 契约形状的 data。
 *
 * <p>为什么不直接推 {@code AiStreamEvent}：那是**内部**契约的载体（snake_case 语义、字段名按
 * docs/api/openapi-internal.yaml）。对外契约的字段名不同（{@code excerpt → text}、 {@code score_stage → stage}），且
 * Python 未来加字段时内部载体会有 Java 不认识的成员。用一个专门的对外载体， 保证线上字节流只可能是契约里的形状。
 *
 * <p>每个嵌套 record 对应 docs/api/openapi-public.yaml 的一个 {@code *EventData} schema，字段名逐字对齐， 都带 {@code
 * additionalProperties: false} 的语义约束，所以不能多塞字段。
 *
 * @param event 事件名：status / retrieval / token / done / error
 * @param data 该事件的 data 对象
 */
public record ChatStreamFrame(String event, Object data) {

    /** 事件名常量。 */
    public static final String EVENT_STATUS = "status";

    /** 检索事件名。 */
    public static final String EVENT_RETRIEVAL = "retrieval";

    /** 增量正文事件名。 */
    public static final String EVENT_TOKEN = "token";

    /** 终帧事件名。 */
    public static final String EVENT_DONE = "done";

    /** 异常帧事件名。 */
    public static final String EVENT_ERROR = "error";

    /** status 帧，对应 {@code StatusEventData}。 */
    public record Status(String stage) {}

    /** retrieval 帧，对应 {@code RetrievalEventData}。 */
    public record Retrieval(List<CitationVO> citations) {}

    /** token 帧，对应 {@code TokenEventData}。 */
    public record Token(String content) {}

    /**
     * done 帧，对应 {@code DoneEventData}。
     *
     * <p>{@code directMessageId} / {@code directContent} 只在 {@code mode=both} 时出现，故用 NON_NULL 省略 ——
     * 契约里它们不是 required，但一旦出现就必须有值。
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Done(
            String messageId,
            Map<String, Integer> usage,
            long elapsedMs,
            boolean degraded,
            List<String> suggestions,
            String directMessageId,
            String directContent) {}

    /**
     * error 帧，对应 {@code ErrorEventData}。
     *
     * <p>{@code fallback} 可空（NON_NULL 省略）。
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Error(int code, String message, String fallback) {}
}
