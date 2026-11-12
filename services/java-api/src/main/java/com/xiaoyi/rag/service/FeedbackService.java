package com.xiaoyi.rag.service;

import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.common.support.MessageJsonCodec;
import com.xiaoyi.rag.model.dto.CandidateDecisionRequest;
import com.xiaoyi.rag.model.dto.FeedbackRequest;
import com.xiaoyi.rag.model.entity.Conversation;
import com.xiaoyi.rag.model.entity.EvalCandidate;
import com.xiaoyi.rag.model.entity.Feedback;
import com.xiaoyi.rag.model.entity.Message;
import com.xiaoyi.rag.model.vo.EvalCandidateVO;
import com.xiaoyi.rag.model.vo.FeedbackSummaryVO;
import com.xiaoyi.rag.repository.ConversationRepository;
import com.xiaoyi.rag.repository.EvalCandidateRepository;
import com.xiaoyi.rag.repository.FeedbackRepository;
import com.xiaoyi.rag.repository.MessageRepository;
import java.util.List;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** 反馈与候选池共用事务边界；Controller 只负责契约封装。 */
@Service
public class FeedbackService {

    /** 汇总扫描的分页大小：按会话翻页，避免一次把某会话的全部消息读进内存。 */
    private static final int SUMMARY_PAGE_SIZE = 200;

    private final MessageRepository messages;
    private final ConversationRepository conversations;
    private final FeedbackRepository feedbacks;
    private final EvalCandidateRepository candidateRepository;
    private final MessageJsonCodec jsonCodec;

    public FeedbackService(
            MessageRepository messages,
            ConversationRepository conversations,
            FeedbackRepository feedbacks,
            EvalCandidateRepository candidateRepository,
            MessageJsonCodec jsonCodec) {
        this.messages = messages;
        this.conversations = conversations;
        this.feedbacks = feedbacks;
        this.candidateRepository = candidateRepository;
        this.jsonCodec = jsonCodec;
    }

    /**
     * 提交 👍 / 👎。
     *
     * <p>消息归属只能沿「消息 → 会话 → user_id」推导，feedback 表本身没有归属列。 别人的消息与不存在的消息走同一个 40407 分支，不泄露消息是否存在。
     *
     * @param userId 当前用户
     * @param id 消息 id（契约里是字符串）
     * @param request 评分、标签、备注
     */
    @Transactional
    public void submit(Long userId, String id, FeedbackRequest request) {
        if (request == null
                || !("up".equals(request.rating()) || "down".equals(request.rating()))) {
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "rating 只能是 up / down");
        }
        if (request.tags() != null && request.tags().stream().anyMatch(tag -> tag == null)) {
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "tags 必须是字符串数组");
        }
        Message message =
                messages.findAliveByIdForUpdate(parseId(id, ErrorCode.MESSAGE_NOT_FOUND))
                        .orElseThrow(this::messageNotFound);
        if (!Message.ROLE_ASSISTANT.equals(message.getRole())) {
            throw messageNotFound();
        }
        Conversation conversation =
                conversations
                        .findByIdAndDeletedFalse(message.getConversationId())
                        .filter(row -> userId.equals(row.getUserId()))
                        .orElseThrow(this::messageNotFound);
        Feedback feedback = feedbacks.findByMessageId(message.getId()).orElseGet(Feedback::new);
        feedback.setMessageId(message.getId());
        feedback.setRating(request.rating());
        feedback.setTagsJson(jsonCodec.write(request.tags() == null ? List.of() : request.tags()));
        feedback.setComment(request.comment());
        feedbacks.save(feedback);
        message.setFeedback(request.rating());
        messages.save(message);

        if ("down".equals(request.rating())
                && !candidateRepository.existsByMessageId(message.getId())) {
            Message question =
                    messages.findFirstByConversationIdAndRoleAndDeletedFalseAndIdLessThanOrderByIdDesc(
                                    conversation.getId(), Message.ROLE_USER, message.getId())
                            .orElseThrow(
                                    () ->
                                            new ApiException(
                                                    ErrorCode.INVALID_PARAM.getCode(),
                                                    "该回答缺少对应用户提问"));
            EvalCandidate candidate = new EvalCandidate();
            candidate.setMessageId(message.getId());
            candidate.setQuestion(question.getContent());
            candidate.setSource("feedback");
            candidate.setStatus("pending");
            candidateRepository.save(candidate);
        }
    }

    /**
     * 当前用户自己的反馈汇总。
     *
     * <p>feedback 表没有 user_id，FeedbackRepository 也不在本切片可改范围内，所以这里不用全表计数： 先取该用户未删除的会话，再按会话翻页读未删除消息，
     * 按 {@code message.feedback} 列（每次提交都会同步写入）统计 up / down。候选数直接用仓储里的三表归属查询， 与候选列表口径完全一致。
     *
     * @param userId 当前用户
     * @return 该用户的总量、好评、差评与待处理候选数
     */
    @Transactional(readOnly = true)
    public FeedbackSummaryVO summary(Long userId) {
        long up = 0;
        long down = 0;
        for (Conversation conversation :
                conversations.findByUserIdAndDeletedFalseOrderByUpdatedAtDesc(userId)) {
            for (int page = 0; ; page++) {
                List<Message> batch =
                        messages.findByConversationIdAndDeletedFalseOrderByCreatedAtAscIdAsc(
                                conversation.getId(), PageRequest.of(page, SUMMARY_PAGE_SIZE));
                for (Message message : batch) {
                    if ("up".equals(message.getFeedback())) {
                        up++;
                    } else if ("down".equals(message.getFeedback())) {
                        down++;
                    }
                }
                if (batch.size() < SUMMARY_PAGE_SIZE) {
                    break;
                }
            }
        }
        return new FeedbackSummaryVO(
                up + down, up, down, candidateRepository.countOwnedByStatus(userId, "pending"));
    }

    /**
     * 当前用户自己的 badcase 候选池。
     *
     * @param userId 当前用户
     * @return 候选列表，按创建时间倒序
     */
    @Transactional(readOnly = true)
    public List<EvalCandidateVO> candidates(Long userId) {
        return candidateRepository.findOwnedBy(userId).stream()
                .map(
                        row ->
                                new EvalCandidateVO(
                                        String.valueOf(row.getId()),
                                        row.getQuestion(),
                                        row.getSource(),
                                        row.getStatus(),
                                        row.getCreatedAt(),
                                        // 空串归一成 null：库里理论上不会存空串（decide 会写 null），
                                        // 但手工改过库时两者语义相同，读侧统一成一种形状。
                                        row.getKeywords() == null || row.getKeywords().isEmpty()
                                                ? null
                                                : row.getKeywords()))
                .toList();
    }

    /**
     * 采纳 / 忽略候选。
     *
     * <p>先做归属校验再取行：别人的候选与不存在的 id 都返回 40404，不给「存在但无权」这种可枚举的信号。
     *
     * <p>{@code keywords} 只在 {@code status=accepted} 时写入：忽略的候选不会进实验，存关键词没有消费者； 而「采纳但没补关键词」是合法状态 ——
     * 该候选能进实验，只是标 {@code scored:false} 不进 hitRate 分母。
     *
     * @param userId 当前用户
     * @param id 候选 id（契约里是字符串）
     * @param request 目标状态与可选关键词
     */
    @Transactional
    public void decide(Long userId, String id, CandidateDecisionRequest request) {
        if (request == null
                || !("accepted".equals(request.status()) || "ignored".equals(request.status()))) {
            throw new ApiException(
                    ErrorCode.INVALID_PARAM.getCode(), "status 只能是 accepted / ignored");
        }
        Long candidateId = parseId(id, ErrorCode.CANDIDATE_NOT_FOUND);
        if (!candidateRepository.existsOwnedById(candidateId, userId)) {
            throw candidateNotFound();
        }
        EvalCandidate candidate =
                candidateRepository.findById(candidateId).orElseThrow(this::candidateNotFound);
        candidate.setStatus(request.status());
        if ("accepted".equals(request.status())) {
            String keywords = normalizeKeywords(request.keywords());
            // null 表示「这次没补」，保留已有的；空串表示「明确清空」，写回 null。
            if (keywords != null) {
                candidate.setKeywords(keywords.isEmpty() ? null : keywords);
            }
        }
        candidateRepository.save(candidate);
    }

    /**
     * 已采纳候选导出为题库 CSV（`question,keywords` 两列，带 BOM）。
     *
     * <p>为什么导出的是「贴回 questions.csv」的形状而不是 JSON：这一列 keywords 本来就是要人补的， 补完直接进题库当固定题用，比再写一个导入接口省一整条链路。带
     * BOM 是因为要过 Excel。
     *
     * @param userId 当前用户
     * @return CSV 文本（含表头）
     */
    @Transactional(readOnly = true)
    public String exportCandidates(Long userId) {
        List<EvalCandidate> rows = candidateRepository.findOwnedByStatus(userId, "accepted");
        StringBuilder csv = new StringBuilder("\ufeffquestion,keywords\r\n");
        for (EvalCandidate row : rows) {
            csv.append(quote(row.getQuestion()))
                    .append(',')
                    .append(quote(row.getKeywords() == null ? "" : row.getKeywords()))
                    .append("\r\n");
        }
        return csv.toString();
    }

    /** CSV 字段转义：含逗号/引号/换行时必须整段加引号，内部引号翻倍。 */
    private static String quote(String value) {
        String text = value == null ? "" : value;
        if (text.indexOf(',') < 0
                && text.indexOf('"') < 0
                && text.indexOf('\n') < 0
                && text.indexOf('\r') < 0) {
            return text;
        }
        return '"' + text.replace("\"", "\"\"") + '"';
    }

    /**
     * 归一化人工填的关键词。
     *
     * @param raw 请求里的原始值
     * @return {@code null} 表示没填（不覆盖已有值）；空串表示明确清空；其余是 trim 后的值
     */
    private static String normalizeKeywords(String raw) {
        if (raw == null) {
            return null;
        }
        String text = raw.strip();
        if (text.length() > 512) {
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "keywords 最多 512 字符");
        }
        return text;
    }

    private ApiException messageNotFound() {
        return new ApiException(
                ErrorCode.MESSAGE_NOT_FOUND.getCode(),
                ErrorCode.MESSAGE_NOT_FOUND.getDefaultMessage());
    }

    private ApiException candidateNotFound() {
        return new ApiException(
                ErrorCode.CANDIDATE_NOT_FOUND.getCode(),
                ErrorCode.CANDIDATE_NOT_FOUND.getDefaultMessage());
    }

    private Long parseId(String id, ErrorCode notFound) {
        try {
            long value = Long.parseLong(id);
            if (value > 0) {
                return value;
            }
        } catch (NumberFormatException ignored) {
            // 契约 ID 是字符串；格式不符也按资源不存在处理。
        }
        throw new ApiException(notFound.getCode(), notFound.getDefaultMessage());
    }
}
