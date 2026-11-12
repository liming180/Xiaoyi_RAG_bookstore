package com.xiaoyi.rag.service.impl;

import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.common.support.MessageJsonCodec;
import com.xiaoyi.rag.model.dto.CreateConversationRequest;
import com.xiaoyi.rag.model.entity.Conversation;
import com.xiaoyi.rag.model.entity.Message;
import com.xiaoyi.rag.model.vo.ConversationVO;
import com.xiaoyi.rag.model.vo.MessageVO;
import com.xiaoyi.rag.repository.ConversationRepository;
import com.xiaoyi.rag.repository.MessageRepository;
import com.xiaoyi.rag.service.ConversationService;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 会话与消息实现。
 *
 * <p>三处易踩的边界：
 *
 * <ul>
 *   <li>会话不存在一律 {@code 40406}（契约 {@code listMessages} / {@code clearMessages} 的 404 就是它）， 包括「存在但
 *       deleted=true」——对上层等同于不存在。
 *   <li>{@code limit} 越界抛 {@code 40001}（手册 §6「分页参数非法（limit>200）要 400」）， 在 Service 里挡而不是靠 Controller
 *       的 {@code @Min/@Max}，因为 {@code @RequestParam} 校验需要 类上再加 {@code @Validated}，会牵连其它端点。
 *   <li>新建会话后手动 {@code touch} 一次 {@code updated_at}：库里 {@code created_at} 与 {@code updated_at}
 *       是同一秒时，列表排序不稳定，前端刚建的会话可能排不到最前。
 * </ul>
 */
@Service
public class ConversationServiceImpl implements ConversationService {

    /** 分页默认条数。 */
    private static final int DEFAULT_LIMIT = 50;

    /** 分页上限，超过按非法参数处理。 */
    private static final int MAX_LIMIT = 200;

    private final ConversationRepository conversationRepository;

    private final MessageRepository messageRepository;

    private final MessageJsonCodec jsonCodec;

    public ConversationServiceImpl(
            ConversationRepository conversationRepository,
            MessageRepository messageRepository,
            MessageJsonCodec jsonCodec) {
        this.conversationRepository = conversationRepository;
        this.messageRepository = messageRepository;
        this.jsonCodec = jsonCodec;
    }

    @Override
    @Transactional(readOnly = true)
    public List<ConversationVO> list(Long userId) {
        List<Conversation> rows =
                conversationRepository.findByUserIdAndDeletedFalseOrderByUpdatedAtDesc(userId);
        List<ConversationVO> result = new ArrayList<>(rows.size());
        for (Conversation row : rows) {
            result.add(toVO(row));
        }
        return result;
    }

    @Override
    @Transactional
    public ConversationVO create(Long userId, CreateConversationRequest request) {
        Conversation entity = new Conversation();
        entity.setUserId(userId);
        String title = request == null ? null : request.title();
        entity.setTitle(title == null || title.isBlank() ? "新会话" : title.trim());
        Conversation saved = conversationRepository.save(entity);
        // 同一秒内 created_at == updated_at 会让排序抖动，这里显式推进一秒，保证新会话稳定排最前。
        conversationRepository.touch(saved.getId(), Instant.now().getEpochSecond() + 1L);
        saved.setUpdatedAt(Instant.now().getEpochSecond() + 1L);
        return toVO(saved);
    }

    @Override
    @Transactional
    public void delete(Long userId, Long conversationId) {
        Conversation conversation = requireConversation(userId, conversationId);
        // 先删消息再删会话：手册 §6「软删，同时把消息标记删除」。
        messageRepository.softDeleteByConversationId(conversation.getId());
        conversationRepository.softDeleteById(conversation.getId());
    }

    @Override
    @Transactional(readOnly = true)
    public List<MessageVO> listMessages(
            Long userId, Long conversationId, Integer limit, Long before) {
        Conversation conversation = requireConversation(userId, conversationId);
        int size = normalizeLimit(limit);
        Pageable pageable = PageRequest.of(0, size);
        List<Message> rows =
                before == null
                        ? messageRepository
                                .findByConversationIdAndDeletedFalseOrderByCreatedAtAscIdAsc(
                                        conversation.getId(), pageable)
                        : messageRepository
                                .findByConversationIdAndDeletedFalseAndCreatedAtLessThanOrderByCreatedAtAscIdAsc(
                                        conversation.getId(), before, pageable);
        List<MessageVO> result = new ArrayList<>(rows.size());
        for (Message row : rows) {
            result.add(toVO(row));
        }
        return result;
    }

    @Override
    @Transactional
    public void clearMessages(Long userId, Long conversationId) {
        Conversation conversation = requireConversation(userId, conversationId);
        messageRepository.softDeleteByConversationId(conversation.getId());
        // 清空也算一次变更，把会话顶到列表最前，符合用户直觉。
        conversationRepository.touch(conversation.getId(), Instant.now().getEpochSecond());
    }

    /**
     * 取会话，不存在或已软删都抛 {@code 40406}。
     *
     * @param userId 当前用户
     * @param conversationId 会话 id
     * @return 会话实体
     */
    private Conversation requireConversation(Long userId, Long conversationId) {
        Conversation conversation =
                conversationRepository
                        .findByIdAndDeletedFalse(conversationId)
                        .orElseThrow(
                                () ->
                                        new ApiException(
                                                ErrorCode.CONVERSATION_NOT_FOUND.getCode(),
                                                ErrorCode.CONVERSATION_NOT_FOUND
                                                        .getDefaultMessage()));
        if (!userId.equals(conversation.getUserId())) {
            // 越权访问也按「不存在」处理，不泄漏别人会话的存在性。
            throw new ApiException(
                    ErrorCode.CONVERSATION_NOT_FOUND.getCode(),
                    ErrorCode.CONVERSATION_NOT_FOUND.getDefaultMessage());
        }
        return conversation;
    }

    /**
     * 校验并归一化分页条数。
     *
     * @param limit 入参，可为 null
     * @return 合法条数
     */
    private int normalizeLimit(Integer limit) {
        if (limit == null) {
            return DEFAULT_LIMIT;
        }
        if (limit < 1 || limit > MAX_LIMIT) {
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "limit 需在 1-200 之间");
        }
        return limit;
    }

    /**
     * 会话实体转视图。
     *
     * @param entity 实体
     * @return 视图
     */
    private ConversationVO toVO(Conversation entity) {
        long alive = conversationRepository.countAliveMessages(entity.getId());
        return new ConversationVO(
                String.valueOf(entity.getId()),
                entity.getTitle(),
                entity.getCreatedAt(),
                entity.getUpdatedAt(),
                (int) alive);
    }

    /**
     * 消息实体转视图。
     *
     * @param entity 实体
     * @return 视图
     */
    private MessageVO toVO(Message entity) {
        return new MessageVO(
                String.valueOf(entity.getId()),
                String.valueOf(entity.getConversationId()),
                entity.getRole(),
                entity.getContent(),
                entity.getCreatedAt(),
                jsonCodec.readCitations(entity.getCitationsJson()),
                jsonCodec.readTrace(entity.getRetrievalTraceJson()),
                jsonCodec.readUsage(entity.getUsageJson()),
                entity.getElapsedMs() == null ? 0L : entity.getElapsedMs(),
                Boolean.TRUE.equals(entity.getDegraded()),
                // N2：从 suggestions_json 读回。null（N2 之前的历史行）降级成空列表，
                // 契约里 Message.suggestions 是 required 数组，给 null 会直接违约。
                jsonCodec.readSuggestions(entity.getSuggestionsJson()),
                entity.getFeedback(),
                null);
    }
}
