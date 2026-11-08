package com.xiaoyi.rag.service;

import com.xiaoyi.rag.client.dto.AiCitation;
import com.xiaoyi.rag.model.dto.ChatContext;

/**
 * 问答落库：把一轮问答的用户消息与助手消息写进 message 表。
 *
 * <p>单独成一个 bean 而不是 {@code ChatServiceImpl} 的私有方法，是因为 {@code @Transactional} 靠 Spring AOP 代理生效，
 * 类内自调用不会走代理 —— 写在同一个类里的事务注解等于没写。
 *
 * <p>本接口的方法**必须**在落库线程池里被调用（手册 §7：「不许在 SSE 线程里做数据库写入」）。
 */
public interface ChatPersistService {

    /**
     * 写一轮问答的两条消息，并推进会话的 updated_at / 标题。
     *
     * @param context 编排上下文
     * @param content 助手回答正文（可能是空串，例如上游在首个 token 前就失败了）
     * @param citations 本轮引用（内部形状）
     * @param usage token 用量，可空
     * @param elapsedMs 耗时毫秒
     * @param degraded 是否走了降级路径
     * @param suggestions 追问推荐（N2），可空／空列表；落库后刷新页面仍能回放 chips
     * @return 助手消息的数据库 id
     */
    Long persistTurn(
            ChatContext context,
            String content,
            java.util.List<AiCitation> citations,
            java.util.Map<String, Integer> usage,
            long elapsedMs,
            boolean degraded,
            java.util.List<String> suggestions);
}
