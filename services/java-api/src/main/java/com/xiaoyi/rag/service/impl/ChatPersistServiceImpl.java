package com.xiaoyi.rag.service.impl;

import com.xiaoyi.rag.client.dto.AiCitation;
import com.xiaoyi.rag.common.support.CitationMapper;
import com.xiaoyi.rag.common.support.MessageJsonCodec;
import com.xiaoyi.rag.model.dto.ChatContext;
import com.xiaoyi.rag.model.entity.Conversation;
import com.xiaoyi.rag.model.entity.Message;
import com.xiaoyi.rag.model.vo.CitationVO;
import com.xiaoyi.rag.model.vo.RetrievalTraceVO;
import com.xiaoyi.rag.model.vo.TraceRowVO;
import com.xiaoyi.rag.repository.ConversationRepository;
import com.xiaoyi.rag.repository.MessageRepository;
import com.xiaoyi.rag.service.ChatPersistService;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 问答落库实现。
 *
 * <p>两个容易踩的点：
 *
 * <ul>
 *   <li>用户消息与助手消息必须写在**同一个事务**里：只写进一条会让「会话消息数」与「对话轮次」对不上， 前端回看时会看到一条没有提问的孤零零回答。
 *   <li>检索轨迹在 J3 阶段由引用列表反推（Python 的 retrieval 事件只给最终 top-k，没有候选全集）。 等 A3 提供候选全集后只改 {@link
 *       #buildTrace} 一处。
 * </ul>
 */
@Service
public class ChatPersistServiceImpl implements ChatPersistService {

    /** 会话默认标题，与前端 mock 的「新会话」一致。 */
    private static final String DEFAULT_TITLE = "新会话";

    /** 会话标题取问题前若干字。 */
    private static final int TITLE_MAX = 20;

    /**
     * 检索轨迹的建库参数占位值。
     *
     * <p>J3 阶段还没有 manifest（J4 才写 index_task），先用功能规格 F02 的默认 180/30。 契约要求 chunkSize ∈
     * [50,1000]、overlap ≥ 0，两个值都合法。
     */
    private static final int TRACE_CHUNK_SIZE = 180;

    private static final int TRACE_OVERLAP = 30;

    private final MessageRepository messageRepository;

    private final ConversationRepository conversationRepository;

    private final MessageJsonCodec jsonCodec;

    private final CitationMapper citationMapper;

    public ChatPersistServiceImpl(
            MessageRepository messageRepository,
            ConversationRepository conversationRepository,
            MessageJsonCodec jsonCodec,
            CitationMapper citationMapper) {
        this.messageRepository = messageRepository;
        this.conversationRepository = conversationRepository;
        this.jsonCodec = jsonCodec;
        this.citationMapper = citationMapper;
    }

    @Override
    @Transactional
    public Long persistTurn(
            ChatContext context,
            String content,
            List<AiCitation> citations,
            Map<String, Integer> usage,
            long elapsedMs,
            boolean degraded,
            List<String> suggestions) {
        long now = Instant.now().getEpochSecond();

        Message userMessage = new Message();
        userMessage.setConversationId(context.conversationId());
        userMessage.setRole(Message.ROLE_USER);
        userMessage.setContent(context.question());
        userMessage.setMode(context.mode());
        userMessage.setTopK(context.k());
        userMessage.setElapsedMs(0L);
        userMessage.setDegraded(false);
        userMessage.setCreatedAt(now);
        messageRepository.save(userMessage);

        List<CitationVO> citationVOs = citationMapper.toVOs(citations);
        Message assistant = new Message();
        assistant.setConversationId(context.conversationId());
        assistant.setRole(Message.ROLE_ASSISTANT);
        assistant.setContent(content == null ? "" : content);
        assistant.setMode(context.mode());
        assistant.setTopK(context.k());
        assistant.setCitationsJson(jsonCodec.write(citationVOs));
        assistant.setRetrievalTraceJson(jsonCodec.write(buildTrace(context, citationVOs)));
        assistant.setUsageJson(jsonCodec.write(usage));
        // N2：追问推荐落库。空列表存 NULL 而不是 '[]' —— 历史行没有这一列，
        // 让「没有推荐」和「N2 之前的老数据」在库里长得一样，读侧只需一条降级分支。
        assistant.setSuggestionsJson(
                suggestions == null || suggestions.isEmpty()
                        ? null
                        : jsonCodec.write(List.copyOf(suggestions)));
        assistant.setElapsedMs(elapsedMs);
        assistant.setDegraded(degraded);
        assistant.setCreatedAt(now);
        Message saved = messageRepository.save(assistant);

        conversationRepository.touch(context.conversationId(), now);
        updateTitleIfDefault(context.conversationId(), context.question());
        return saved.getId();
    }

    /**
     * 用本轮引用构造检索轨迹。
     *
     * <p>Python 的 retrieval 事件只给最终 top-k，没有「候选全集 + 前 k 界线」，所以这里按「进入 top-k 的 全部 retrieved=true」落库。等
     * A3 阶段 Python 提供候选全集后，只需改本方法。
     *
     * @param context 上下文
     * @param citations 对外引用列表
     * @return 轨迹；无引用时返回 null（契约允许 {@code trace: null}）
     */
    private RetrievalTraceVO buildTrace(ChatContext context, List<CitationVO> citations) {
        if (citations == null || citations.isEmpty()) {
            return null;
        }
        List<TraceRowVO> rows = new ArrayList<>(citations.size());
        for (int i = 0; i < citations.size(); i++) {
            CitationVO cite = citations.get(i);
            rows.add(
                    new TraceRowVO(
                            i + 1,
                            cite.chunkId(),
                            cite.docId(),
                            cite.docTitle(),
                            cite.headingPath(),
                            cite.text(),
                            cite.start(),
                            cite.end(),
                            cite.score(),
                            true,
                            cite.kind(),
                            cite.verified()));
        }
        return new RetrievalTraceVO(
                context.question(), context.k(), TRACE_CHUNK_SIZE, TRACE_OVERLAP, rows);
    }

    /** 会话仍是默认标题时，用首问前 20 字命名（与前端 mock 一致）。 */
    private void updateTitleIfDefault(Long conversationId, String question) {
        Conversation conversation =
                conversationRepository.findByIdAndDeletedFalse(conversationId).orElse(null);
        if (conversation == null || !DEFAULT_TITLE.equals(conversation.getTitle())) {
            return;
        }
        conversation.setTitle(titleOf(question));
        conversationRepository.save(conversation);
    }

    private String titleOf(String question) {
        if (question == null || question.isBlank()) {
            return DEFAULT_TITLE;
        }
        String trimmed = question.trim();
        return trimmed.length() <= TITLE_MAX ? trimmed : trimmed.substring(0, TITLE_MAX);
    }
}
