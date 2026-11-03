package com.xiaoyi.rag.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.common.support.MessageJsonCodec;
import com.xiaoyi.rag.model.dto.CandidateDecisionRequest;
import com.xiaoyi.rag.model.dto.FeedbackRequest;
import com.xiaoyi.rag.model.entity.Conversation;
import com.xiaoyi.rag.model.entity.EvalCandidate;
import com.xiaoyi.rag.model.entity.Feedback;
import com.xiaoyi.rag.model.entity.Message;
import com.xiaoyi.rag.repository.ConversationRepository;
import com.xiaoyi.rag.repository.EvalCandidateRepository;
import com.xiaoyi.rag.repository.FeedbackRepository;
import com.xiaoyi.rag.repository.MessageRepository;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class FeedbackServiceTest {
    private final MessageRepository messages = mock(MessageRepository.class);
    private final ConversationRepository conversations = mock(ConversationRepository.class);
    private final FeedbackRepository feedbacks = mock(FeedbackRepository.class);
    private final EvalCandidateRepository candidates = mock(EvalCandidateRepository.class);
    private final MessageJsonCodec codec = mock(MessageJsonCodec.class);
    private final FeedbackService service =
            new FeedbackService(messages, conversations, feedbacks, candidates, codec);
    private Message assistant;

    @BeforeEach
    void setup() {
        assistant = new Message();
        assistant.setId(12L);
        assistant.setConversationId(2L);
        assistant.setRole(Message.ROLE_ASSISTANT);
        when(messages.findAliveByIdForUpdate(12L)).thenReturn(Optional.of(assistant));
        when(conversations.findByIdAndDeletedFalse(2L)).thenReturn(Optional.of(new Conversation()));
        when(codec.write(any())).thenReturn("[\"答非所问\"]");
    }

    @Test
    void downPersistsDetailsAndUsesPrecedingQuestion() {
        Message question = new Message();
        question.setContent("上一轮问题");
        when(messages.findFirstByConversationIdAndRoleAndDeletedFalseAndIdLessThanOrderByIdDesc(
                        2L, "user", 12L))
                .thenReturn(Optional.of(question));
        service.submit("12", new FeedbackRequest("down", List.of("答非所问"), "需要改进"));
        ArgumentCaptor<Feedback> feedback = ArgumentCaptor.forClass(Feedback.class);
        verify(feedbacks).save(feedback.capture());
        assertThat(feedback.getValue().getRating()).isEqualTo("down");
        assertThat(feedback.getValue().getTagsJson()).isEqualTo("[\"答非所问\"]");
        assertThat(feedback.getValue().getComment()).isEqualTo("需要改进");
        ArgumentCaptor<EvalCandidate> candidate = ArgumentCaptor.forClass(EvalCandidate.class);
        verify(candidates).save(candidate.capture());
        assertThat(candidate.getValue().getQuestion()).isEqualTo("上一轮问题");
        assertThat(candidate.getValue().getSource()).isEqualTo("feedback");
        assertThat(candidate.getValue().getStatus()).isEqualTo("pending");
        assertThat(assistant.getFeedback()).isEqualTo("down");
    }

    @Test
    void repeatedDownUpdatesFeedbackAndDoesNotResetDecidedCandidate() {
        Feedback existing = new Feedback();
        when(feedbacks.findByMessageId(12L)).thenReturn(Optional.of(existing));
        when(candidates.existsByMessageId(12L)).thenReturn(true);
        service.submit("12", new FeedbackRequest("down", null, "再次反馈"));
        verify(feedbacks).save(existing);
        verify(candidates, never()).save(any());
        verify(messages, never())
                .findFirstByConversationIdAndRoleAndDeletedFalseAndIdLessThanOrderByIdDesc(
                        any(), any(), any());
    }

    @Test
    void rejectsUserMessagesDeletedConversationsAndInvalidInput() {
        assistant.setRole("user");
        assertCode(() -> service.submit("12", new FeedbackRequest("up", null, null)), 40407);
        assistant.setRole("assistant");
        when(conversations.findByIdAndDeletedFalse(2L)).thenReturn(Optional.empty());
        assertCode(() -> service.submit("12", new FeedbackRequest("up", null, null)), 40407);
        assertCode(() -> service.submit("999", new FeedbackRequest("up", null, null)), 40407);
        assertCode(() -> service.submit("12", null), 40001);
        assertCode(() -> service.submit("12", new FeedbackRequest("other", null, null)), 40001);
    }

    @Test
    void decisionsValidateAndPersistAndSummaryCountsPendingOnly() {
        EvalCandidate candidate = new EvalCandidate();
        when(candidates.findById(8L)).thenReturn(Optional.of(candidate));
        service.decide("8", new CandidateDecisionRequest("accepted"));
        assertThat(candidate.getStatus()).isEqualTo("accepted");
        service.decide("8", new CandidateDecisionRequest("ignored"));
        assertThat(candidate.getStatus()).isEqualTo("ignored");
        verify(candidates, times(2)).save(candidate);
        assertCode(() -> service.decide("8", new CandidateDecisionRequest("pending")), 40001);
        assertCode(() -> service.decide("999", new CandidateDecisionRequest("accepted")), 40404);
        when(feedbacks.count()).thenReturn(5L);
        when(feedbacks.countByRating("up")).thenReturn(2L);
        when(feedbacks.countByRating("down")).thenReturn(3L);
        when(candidates.countByStatus("pending")).thenReturn(1L);
        assertThat(service.summary().total()).isEqualTo(5);
        assertThat(service.summary().up()).isEqualTo(2);
        assertThat(service.summary().down()).isEqualTo(3);
        assertThat(service.summary().candidates()).isEqualTo(1);
    }

    private void assertCode(Runnable action, int code) {
        assertThatThrownBy(action::run)
                .isInstanceOfSatisfying(
                        ApiException.class, error -> assertThat(error.getCode()).isEqualTo(code));
    }
}
