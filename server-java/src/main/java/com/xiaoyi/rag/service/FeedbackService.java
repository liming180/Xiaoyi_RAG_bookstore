package com.xiaoyi.rag.service;

import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.common.support.MessageJsonCodec;
import com.xiaoyi.rag.model.dto.CandidateDecisionRequest;
import com.xiaoyi.rag.model.dto.FeedbackRequest;
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
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** 反馈与候选池共用事务边界；Controller 只负责契约封装。 */
@Service
public class FeedbackService {
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

    @Transactional
    public void submit(String id, FeedbackRequest request) {
        if (request == null
                || !("up".equals(request.rating()) || "down".equals(request.rating()))) {
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "rating 只能是 up / down");
        }
        if (request.tags() != null && request.tags().stream().anyMatch(tag -> tag == null)) {
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "tags 必须是字符串数组");
        }
        Message message =
                messages.findAliveByIdForUpdate(parseId(id, ErrorCode.MESSAGE_NOT_FOUND))
                        .orElseThrow(
                                () ->
                                        new ApiException(
                                                ErrorCode.MESSAGE_NOT_FOUND.getCode(),
                                                ErrorCode.MESSAGE_NOT_FOUND.getDefaultMessage()));
        if (!Message.ROLE_ASSISTANT.equals(message.getRole())
                || conversations.findByIdAndDeletedFalse(message.getConversationId()).isEmpty()) {
            throw new ApiException(
                    ErrorCode.MESSAGE_NOT_FOUND.getCode(),
                    ErrorCode.MESSAGE_NOT_FOUND.getDefaultMessage());
        }
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
                                    message.getConversationId(), Message.ROLE_USER, message.getId())
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

    @Transactional(readOnly = true)
    public FeedbackSummaryVO summary() {
        return new FeedbackSummaryVO(
                feedbacks.count(),
                feedbacks.countByRating("up"),
                feedbacks.countByRating("down"),
                candidateRepository.countByStatus("pending"));
    }

    @Transactional(readOnly = true)
    public List<EvalCandidateVO> candidates() {
        return candidateRepository.findAllByOrderByCreatedAtDescIdDesc().stream()
                .map(
                        row ->
                                new EvalCandidateVO(
                                        String.valueOf(row.getId()),
                                        row.getQuestion(),
                                        row.getSource(),
                                        row.getStatus(),
                                        row.getCreatedAt()))
                .toList();
    }

    @Transactional
    public void decide(String id, CandidateDecisionRequest request) {
        if (request == null
                || !("accepted".equals(request.status()) || "ignored".equals(request.status()))) {
            throw new ApiException(
                    ErrorCode.INVALID_PARAM.getCode(), "status 只能是 accepted / ignored");
        }
        EvalCandidate candidate =
                candidateRepository
                        .findById(parseId(id, ErrorCode.CANDIDATE_NOT_FOUND))
                        .orElseThrow(
                                () ->
                                        new ApiException(
                                                ErrorCode.CANDIDATE_NOT_FOUND.getCode(),
                                                ErrorCode.CANDIDATE_NOT_FOUND.getDefaultMessage()));
        candidate.setStatus(request.status());
        candidateRepository.save(candidate);
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
