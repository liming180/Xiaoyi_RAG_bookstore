package com.xiaoyi.rag.model.vo;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.List;
import java.util.Map;

/**
 * 消息视图，对应契约 {@code components.schemas.Message}。
 *
 * <p>契约 required 12 项且 {@code additionalProperties: false}，其中 {@code trace} / {@code usage} /
 * {@code feedback} 是「可空但必须出现」—— 所以本类**不加类级 {@code @JsonInclude(NON_NULL)}**，只在 {@code error} 上单独声明，
 * 否则 {@code null} 会被省略，契约校验直接失败。
 *
 * @param id 消息 id
 * @param conversationId 所属会话 id
 * @param role user / assistant
 * @param content 正文
 * @param createdAt 创建时间（Unix 秒）
 * @param citations 引用列表，无引用时是空数组而不是 null
 * @param trace 检索轨迹，纯直答时为 null
 * @param usage token 用量，无则 null
 * @param elapsedMs 耗时毫秒（时长，不是时间戳）
 * @param degraded 是否走了降级直答
 * @param suggestions 追问推荐，无则空数组
 * @param feedback 反馈 up / down，未反馈为 null
 * @param error 生成失败摘要，正常为 null 且不输出
 */
public record MessageVO(
        String id,
        String conversationId,
        String role,
        String content,
        Long createdAt,
        List<CitationVO> citations,
        Object trace,
        Map<String, Integer> usage,
        Long elapsedMs,
        Boolean degraded,
        List<String> suggestions,
        String feedback,
        @JsonInclude(JsonInclude.Include.NON_NULL) String error) {

    /**
     * 造一条「用户提问」消息：契约要求的可空字段全部显式给空值，避免前端拿到 undefined。
     *
     * @param id 消息 id
     * @param conversationId 会话 id
     * @param content 提问正文
     * @param createdAt 创建时间（Unix 秒）
     * @return 用户消息视图
     */
    public static MessageVO user(String id, String conversationId, String content, Long createdAt) {
        return new MessageVO(
                id,
                conversationId,
                "user",
                content,
                createdAt,
                List.of(),
                null,
                null,
                0L,
                false,
                List.of(),
                null,
                null);
    }
}
