package com.xiaoyi.rag.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.xiaoyi.rag.client.AiServiceClient;
import com.xiaoyi.rag.client.dto.AiChatRequest;
import com.xiaoyi.rag.client.dto.AiStreamEvent;
import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.common.support.CitationMapper;
import com.xiaoyi.rag.common.support.MessageJsonCodec;
import com.xiaoyi.rag.config.XiaoyiProperties;
import com.xiaoyi.rag.model.dto.ChatContext;
import com.xiaoyi.rag.model.entity.Conversation;
import com.xiaoyi.rag.model.entity.Message;
import com.xiaoyi.rag.repository.ConversationRepository;
import com.xiaoyi.rag.repository.MessageRepository;
import com.xiaoyi.rag.service.impl.ChatServiceImpl;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/**
 * H3 问答收尾门禁：落库失败不发成功 done、取消能传到上游、trace 严格按归属。
 *
 * <p>施工单 H3 的验收里有一条「数据库写入失败不发成功 done」。之前实现是落库异常只记日志， 仍然发出带 Python 侧 messageId 的 done
 * 帧——前端会当成已保存，刷新即丢，且 trace 必然 404。这里把那条路径钉死。
 */
@ExtendWith(MockitoExtension.class)
class ChatServiceImplTest {

    private static final Long OWNER = 5L;

    private static final Long OTHER = 6L;

    @Mock private AiServiceClient ai;

    @Mock private ConversationRepository conversations;

    @Mock private MessageRepository messages;

    @Mock private ChatPersistService persistService;

    private ChatServiceImpl service;

    private RecordingSink sink;

    @BeforeEach
    void setUp() {
        XiaoyiProperties properties = new XiaoyiProperties();
        MessageJsonCodec codec = new MessageJsonCodec(new ObjectMapper());
        service =
                new ChatServiceImpl(
                        ai,
                        conversations,
                        messages,
                        codec,
                        new CitationMapper(),
                        persistService,
                        properties,
                        Runnable::run);
        sink = new RecordingSink();
    }

    /* ------------------------------------------------------------ 落库失败 */

    @Test
    @DisplayName("落库抛异常：发 error(50000)，不发 done，也不编造 messageId")
    void persistFailureEmitsErrorInsteadOfDone() {
        when(persistService.persistTurn(any(), any(), any(), any(), anyLong(), eq(false), any()))
                .thenThrow(new IllegalStateException("数据库连接池耗尽"));
        AiServiceClient.StreamHandle handle = AiServiceClient.StreamHandle.NOOP;
        when(ai.chatStream(eq(OWNER), any(), any())).thenReturn(handle);

        service.stream(context(), sink);
        listener().onEvent(AiStreamEvent.token("回答正文"));
        listener().onEvent(done("py-m-123"));

        assertThat(sink.done()).isNull();
        assertThat(sink.errors()).hasSize(1);
        assertThat(sink.errors().get(0).code()).isEqualTo(ErrorCode.INTERNAL_ERROR.getCode());
        assertThat(sink.errors().get(0).message()).contains("保存失败");
        assertThat(sink.completed()).isTrue();
    }

    @Test
    @DisplayName("线程池拒绝：同样发 error，不假装保存成功")
    void rejectedPersistTaskEmitsError() {
        Executor rejecting =
                command -> {
                    throw new RejectedExecutionException("队列已满");
                };
        ChatServiceImpl rejectingService =
                new ChatServiceImpl(
                        ai,
                        conversations,
                        messages,
                        new MessageJsonCodec(new ObjectMapper()),
                        new CitationMapper(),
                        persistService,
                        new XiaoyiProperties(),
                        rejecting);
        when(ai.chatStream(eq(OWNER), any(), any())).thenReturn(AiServiceClient.StreamHandle.NOOP);

        rejectingService.stream(context(), sink);
        listener().onEvent(done("py-m-9"));

        assertThat(sink.done()).isNull();
        assertThat(sink.errors()).hasSize(1);
        assertThat(sink.completed()).isTrue();
        verify(persistService, never())
                .persistTurn(any(), any(), any(), any(), anyLong(), eq(false), any());
    }

    /* ------------------------------------------------------------ 成功路径 */

    @Test
    @DisplayName("落库成功：done.messageId 是数据库 id，不是上游的 py-m-*")
    void doneCarriesDatabaseMessageId() {
        when(persistService.persistTurn(any(), any(), any(), any(), anyLong(), eq(false), any()))
                .thenReturn(4321L);
        when(ai.chatStream(eq(OWNER), any(), any())).thenReturn(AiServiceClient.StreamHandle.NOOP);

        service.stream(context(), sink);
        listener().onEvent(AiStreamEvent.token("正文"));
        listener().onEvent(done("py-m-should-not-leak"));

        assertThat(sink.done()).isNotNull();
        assertThat(sink.done().messageId()).isEqualTo("4321");
        assertThat(sink.errors()).isEmpty();
        assertThat(sink.completed()).isTrue();
    }

    @Test
    @DisplayName("重复终态只落库一次：先 done 再 onError 不会写出两条助手消息")
    void duplicateTerminalEventsPersistOnce() {
        when(persistService.persistTurn(any(), any(), any(), any(), anyLong(), anyBoolean(), any()))
                .thenReturn(7L);
        when(ai.chatStream(eq(OWNER), any(), any())).thenReturn(AiServiceClient.StreamHandle.NOOP);

        service.stream(context(), sink);
        listener().onEvent(done("py-m-1"));
        listener().onError(new IllegalStateException("收尾异常"));

        verify(persistService)
                .persistTurn(any(), any(), any(), any(), anyLong(), anyBoolean(), any());
        assertThat(sink.done()).isNotNull();
    }

    @Test
    @DisplayName("上游不可达：走降级 done{degraded:true}，不抛给前端")
    void unavailableUpstreamDegrades() {
        when(ai.chatStream(eq(OWNER), any(), any())).thenThrow(new IllegalStateException("连接被拒绝"));
        when(persistService.persistTurn(any(), any(), any(), any(), anyLong(), eq(true), any()))
                .thenReturn(11L);

        AiServiceClient.StreamHandle handle = service.stream(context(), sink);

        assertThat(handle).isSameAs(AiServiceClient.StreamHandle.NOOP);
        assertThat(sink.done()).isNotNull();
        assertThat(sink.done().degraded()).isTrue();
        assertThat(sink.done().messageId()).isEqualTo("11");
    }

    @Test
    @DisplayName("stream 把上游句柄原样返回，供控制器在断连时 cancel")
    void streamReturnsUpstreamHandleForCancellation() {
        AtomicBoolean cancelled = new AtomicBoolean(false);
        AiServiceClient.StreamHandle handle = () -> cancelled.set(true);
        when(ai.chatStream(eq(OWNER), any(), any())).thenReturn(handle);

        AiServiceClient.StreamHandle returned = service.stream(context(), sink);
        returned.cancel();

        assertThat(cancelled).isTrue();
    }

    /* ------------------------------------------------------------ 追问推荐（N2） */

    @Test
    @DisplayName("N2：上游给的追问既进 done 帧，也原样交给落库（刷新后 chips 不丢）")
    void suggestionsArePersistedAndEmitted() {
        when(persistService.persistTurn(any(), any(), any(), any(), anyLong(), anyBoolean(), any()))
                .thenReturn(99L);
        when(ai.chatStream(eq(OWNER), any(), any())).thenReturn(AiServiceClient.StreamHandle.NOOP);

        service.stream(context(), sink);
        listener()
                .onEvent(
                        AiStreamEvent.done(
                                "py-m-1",
                                Map.of("promptTokens", 12),
                                40L,
                                false,
                                List.of("续借几天？", "最多几本？"),
                                null,
                                null));

        assertThat(sink.done().suggestions()).containsExactly("续借几天？", "最多几本？");
        // 关键：落库那次调用拿到的必须是同一份列表。只在 done 帧里带、不落库，
        // 就是 N2 要修的那个缺陷（刷新页面 chips 全丢）。
        ArgumentCaptor<List<String>> saved = ArgumentCaptor.forClass(List.class);
        verify(persistService)
                .persistTurn(any(), any(), any(), any(), anyLong(), anyBoolean(), saved.capture());
        assertThat(saved.getValue()).containsExactly("续借几天？", "最多几本？");
    }

    @Test
    @DisplayName("N2：追问条数按 max-suggestions 截断，落库与 done 帧用同一份截断结果")
    void suggestionsAreTruncatedOnce() {
        XiaoyiProperties properties = new XiaoyiProperties();
        properties.getChat().setMaxSuggestions(2);
        ChatServiceImpl limited =
                new ChatServiceImpl(
                        ai,
                        conversations,
                        messages,
                        new MessageJsonCodec(new ObjectMapper()),
                        new CitationMapper(),
                        persistService,
                        properties,
                        Runnable::run);
        when(persistService.persistTurn(any(), any(), any(), any(), anyLong(), anyBoolean(), any()))
                .thenReturn(77L);
        when(ai.chatStream(eq(OWNER), any(), any())).thenReturn(AiServiceClient.StreamHandle.NOOP);

        limited.stream(context(), sink);
        listener()
                .onEvent(
                        AiStreamEvent.done(
                                "py-m-1",
                                Map.of("promptTokens", 12),
                                40L,
                                false,
                                List.of("一？", "二？", "三？"),
                                null,
                                null));

        assertThat(sink.done().suggestions()).containsExactly("一？", "二？");
        ArgumentCaptor<List<String>> saved = ArgumentCaptor.forClass(List.class);
        verify(persistService)
                .persistTurn(any(), any(), any(), any(), anyLong(), anyBoolean(), saved.capture());
        // 两处各自截断会埋「气泡上三条、刷新后两条」的雷，这里钉死只截一次。
        assertThat(saved.getValue()).containsExactly("一？", "二？");
    }

    @Test
    @DisplayName("N2：降级路径没有上游 done，追问必须是空列表而不是编造几条")
    void degradedTurnHasNoSuggestions() {
        when(ai.chatStream(eq(OWNER), any(), any())).thenThrow(new IllegalStateException("连接被拒绝"));
        when(persistService.persistTurn(any(), any(), any(), any(), anyLong(), eq(true), any()))
                .thenReturn(12L);

        service.stream(context(), sink);

        assertThat(sink.done().degraded()).isTrue();
        assertThat(sink.done().suggestions()).isEmpty();
    }

    /* ------------------------------------------------------------ 身份 */

    @Test
    @DisplayName("没有身份时不落到默认用户，直接 40100")
    void prepareRejectsMissingIdentity() {
        ChatServiceImpl svc = service;
        assertThatThrownBy(
                        () ->
                                svc.prepare(
                                        new com.xiaoyi.rag.model.dto.ChatCommand(
                                                null, null, "问题", "rag", 3)))
                .isInstanceOf(ApiException.class)
                .extracting(ex -> ((ApiException) ex).getCode())
                .isEqualTo(ErrorCode.UNAUTHENTICATED.getCode());
    }

    @Test
    @DisplayName("别人的消息 trace 等同不存在（40407），不泄漏存在性")
    void traceOfAnotherUsersMessageIsNotFound() {
        Message message = new Message();
        message.setId(88L);
        message.setConversationId(4L);
        Conversation conversation = new Conversation();
        conversation.setId(4L);
        conversation.setUserId(OWNER);
        when(messages.findByIdAndDeletedFalse(88L)).thenReturn(Optional.of(message));
        when(conversations.findByIdAndDeletedFalse(4L)).thenReturn(Optional.of(conversation));

        assertThatThrownBy(() -> service.trace(OTHER, 88L))
                .isInstanceOf(ApiException.class)
                .extracting(ex -> ((ApiException) ex).getCode())
                .isEqualTo(ErrorCode.MESSAGE_NOT_FOUND.getCode());
    }

    /* ------------------------------------------------------------ 辅助 */

    private ChatContext context() {
        return new ChatContext(OWNER, 1L, "问题", "rag", 3, List.of());
    }

    private AiServiceClient.StreamListener listener() {
        ArgumentCaptor<AiServiceClient.StreamListener> captor =
                ArgumentCaptor.forClass(AiServiceClient.StreamListener.class);
        verify(ai).chatStream(eq(OWNER), any(AiChatRequest.class), captor.capture());
        return captor.getValue();
    }

    private static AiStreamEvent done(String upstreamMessageId) {
        return AiStreamEvent.done(
                upstreamMessageId,
                Map.of("promptTokens", 12),
                40L,
                false,
                List.of("追问"),
                null,
                null);
    }

    /** 记录所有帧的 EventSink。 */
    private static final class RecordingSink implements ChatService.EventSink {

        private final List<ChatStreamFrame> frames = new ArrayList<>();

        private boolean completed;

        @Override
        public void emit(ChatStreamFrame frame) {
            frames.add(frame);
        }

        @Override
        public void complete() {
            completed = true;
        }

        @Override
        public void fail(Throwable error) {
            throw new AssertionError("流式接口不应调用 fail", error);
        }

        ChatStreamFrame.Done done() {
            return frames.stream()
                    .filter(f -> ChatStreamFrame.EVENT_DONE.equals(f.event()))
                    .map(f -> (ChatStreamFrame.Done) f.data())
                    .findFirst()
                    .orElse(null);
        }

        List<ChatStreamFrame.Error> errors() {
            return frames.stream()
                    .filter(f -> ChatStreamFrame.EVENT_ERROR.equals(f.event()))
                    .map(f -> (ChatStreamFrame.Error) f.data())
                    .toList();
        }

        boolean completed() {
            return completed;
        }
    }
}
