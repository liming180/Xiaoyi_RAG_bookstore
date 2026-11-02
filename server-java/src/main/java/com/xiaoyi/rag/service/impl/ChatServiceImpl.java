package com.xiaoyi.rag.service.impl;

import com.xiaoyi.rag.client.AiServiceClient;
import com.xiaoyi.rag.client.dto.AiChatRequest;
import com.xiaoyi.rag.client.dto.AiChatRequest.HistoryTurn;
import com.xiaoyi.rag.client.dto.AiCitation;
import com.xiaoyi.rag.client.dto.AiStreamEvent;
import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.common.support.CitationMapper;
import com.xiaoyi.rag.common.support.MessageJsonCodec;
import com.xiaoyi.rag.config.AsyncConfig;
import com.xiaoyi.rag.config.XiaoyiProperties;
import com.xiaoyi.rag.model.dto.ChatCommand;
import com.xiaoyi.rag.model.dto.ChatContext;
import com.xiaoyi.rag.model.entity.Conversation;
import com.xiaoyi.rag.model.entity.Message;
import com.xiaoyi.rag.model.vo.RetrievalTraceVO;
import com.xiaoyi.rag.model.vo.TraceRowVO;
import com.xiaoyi.rag.repository.ConversationRepository;
import com.xiaoyi.rag.repository.MessageRepository;
import com.xiaoyi.rag.service.ChatPersistService;
import com.xiaoyi.rag.service.ChatService;
import com.xiaoyi.rag.service.ChatStreamFrame;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executor;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 问答编排实现，严格按手册 §7 的五步：
 *
 * <ol>
 *   <li>{@link #prepare} 校验 mode / k、取最近 N 轮 history、必要时建会话；
 *   <li>{@link #stream} 调 {@link AiServiceClient}，把事件逐条改写成对外契约形状后透传；
 *   <li>上游 done / error / 抛异常后，把落库任务丢给 {@code chatPersistExecutor}，**不在流线程里写库**；
 *   <li>落库任务写完 assistant 消息后，用**数据库真实 id** 发 done 帧，保证 {@code GET /messages/{id}/trace} 一定查得到；
 *   <li>AI 不可达时降级：不发 error，改发 {@code done{degraded:true}}，HTTP 仍是 200。
 * </ol>
 *
 * <p>为什么 done 帧要等落库完才发：前端拿到 {@code messageId} 会立刻回调 {@code GET /api/v1/messages/{id}/trace}（见
 * {@code frontend/src/features/chat/composables/useChat.ts:113}）。 若 done 先发、落库后到，那次 trace 请求必然
 * 404，用户看到的是「检索过程丢失」。
 */
@Service
public class ChatServiceImpl implements ChatService {

    private static final Logger log = LoggerFactory.getLogger(ChatServiceImpl.class);

    /** 合法回答模式。 */
    private static final List<String> MODES = List.of("rag", "direct", "both");

    /** 契约 ChatRequest.k 的取值区间（docs/api/openapi-public.yaml:1525-1529）。 */
    private static final int MIN_K = 1;

    private static final int MAX_K = 10;

    private static final int DEFAULT_K = 3;

    private static final String DEFAULT_MODE = "rag";

    private static final String DEFAULT_TITLE = "新会话";

    /** 会话标题取问题前若干字，与前端 mock 的截断长度一致。 */
    private static final int TITLE_MAX = 20;

    private final AiServiceClient aiServiceClient;

    private final ConversationRepository conversationRepository;

    private final MessageRepository messageRepository;

    private final MessageJsonCodec jsonCodec;

    private final CitationMapper citationMapper;

    private final ChatPersistService persistService;

    private final XiaoyiProperties properties;

    private final Executor persistExecutor;

    public ChatServiceImpl(
            AiServiceClient aiServiceClient,
            ConversationRepository conversationRepository,
            MessageRepository messageRepository,
            MessageJsonCodec jsonCodec,
            CitationMapper citationMapper,
            ChatPersistService persistService,
            XiaoyiProperties properties,
            @Qualifier(AsyncConfig.CHAT_PERSIST_EXECUTOR) Executor persistExecutor) {
        this.aiServiceClient = aiServiceClient;
        this.conversationRepository = conversationRepository;
        this.messageRepository = messageRepository;
        this.jsonCodec = jsonCodec;
        this.citationMapper = citationMapper;
        this.persistService = persistService;
        this.properties = properties;
        this.persistExecutor = persistExecutor;
    }

    @Override
    @Transactional
    public ChatContext prepare(ChatCommand command) {
        if (command == null) {
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "请求体不能为空");
        }
        String question = command.question() == null ? "" : command.question().trim();
        if (question.isEmpty()) {
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "问题不能为空");
        }
        String mode = normalizeMode(command.mode());
        int k = normalizeK(command.k());
        Long userId = command.userId() == null ? 1L : command.userId();

        Conversation conversation = resolveConversation(userId, command.conversationId(), question);
        List<HistoryTurn> history = loadHistory(conversation.getId());
        return new ChatContext(userId, conversation.getId(), question, mode, k, history);
    }

    @Override
    public void stream(ChatContext context, EventSink sink) {
        StringBuilder answer = new StringBuilder();
        List<AiCitation> collected = Collections.synchronizedList(new ArrayList<>());
        long startedAt = System.currentTimeMillis();
        // 终态只允许触发一次：上游可能先发 done 再因收尾异常回调 onError，重复落库会写出两条助手消息。
        AtomicBoolean terminated = new AtomicBoolean(false);

        AiChatRequest request =
                new AiChatRequest(
                        context.question(),
                        context.history(),
                        context.mode(),
                        context.k(),
                        List.of());

        try {
            aiServiceClient.chatStream(
                    request,
                    new AiServiceClient.StreamListener() {
                        @Override
                        public void onEvent(AiStreamEvent event) {
                            handleEvent(
                                    context, sink, event, answer, collected, startedAt, terminated);
                        }

                        @Override
                        public void onError(Throwable error) {
                            log.warn("AI 流异常，转降级：{}", error.getMessage());
                            degrade(context, sink, answer, collected, startedAt, terminated);
                        }
                    });
        } catch (RuntimeException ex) {
            // 客户端本身在调用期就抛（连不上、熔断打开）：同样走降级，不把异常栈透给前端。
            log.warn("调用 AI 客户端失败，转降级：{}", ex.getMessage());
            degrade(context, sink, answer, collected, startedAt, terminated);
        }
    }

    @Override
    @Transactional(readOnly = true)
    public RetrievalTraceVO trace(Long userId, Long messageId) {
        Message message =
                messageRepository
                        .findByIdAndDeletedFalse(messageId)
                        .orElseThrow(
                                () ->
                                        new ApiException(
                                                ErrorCode.MESSAGE_NOT_FOUND.getCode(),
                                                ErrorCode.MESSAGE_NOT_FOUND.getDefaultMessage()));
        Conversation conversation =
                conversationRepository
                        .findByIdAndDeletedFalse(message.getConversationId())
                        .orElse(null);
        if (conversation == null || (userId != null && !userId.equals(conversation.getUserId()))) {
            // 会话已删或不属于当前用户，等同消息不存在，不泄漏存在性。
            throw new ApiException(
                    ErrorCode.MESSAGE_NOT_FOUND.getCode(),
                    ErrorCode.MESSAGE_NOT_FOUND.getDefaultMessage());
        }
        return toTraceVO(jsonCodec.readTrace(message.getRetrievalTraceJson()));
    }

    /**
     * 降级：不发 error 帧，改发 {@code done{degraded:true}}，HTTP 仍 200（手册 §7 第 ④ 条）。
     *
     * @param context 上下文
     * @param sink 出口
     * @param answer 已累积正文
     * @param collected 已累积引用
     * @param startedAt 起始毫秒
     * @param terminated 终态闸门
     */
    private void degrade(
            ChatContext context,
            EventSink sink,
            StringBuilder answer,
            List<AiCitation> collected,
            long startedAt,
            AtomicBoolean terminated) {
        persistAndFinish(
                context,
                sink,
                answer.toString(),
                new ArrayList<>(collected),
                null,
                System.currentTimeMillis() - startedAt,
                true,
                terminated);
    }

    /**
     * 单事件处理：已知事件改写后立即透传，终态事件转异步落库。
     *
     * @param context 编排上下文
     * @param sink 事件出口
     * @param event 上游事件
     * @param answer 累积正文
     * @param collected 累积引用
     * @param startedAt 起始毫秒
     * @param terminated 终态闸门
     */
    private void handleEvent(
            ChatContext context,
            EventSink sink,
            AiStreamEvent event,
            StringBuilder answer,
            List<AiCitation> collected,
            long startedAt,
            AtomicBoolean terminated) {
        if (event == null) {
            return;
        }
        String name = event.event() == null ? "" : event.event();
        switch (name) {
            case ChatStreamFrame.EVENT_STATUS -> {
                if (event.stage() != null) {
                    sink.emit(
                            new ChatStreamFrame(
                                    ChatStreamFrame.EVENT_STATUS,
                                    new ChatStreamFrame.Status(event.stage())));
                }
            }
            case ChatStreamFrame.EVENT_RETRIEVAL -> {
                if (event.citations() != null) {
                    collected.clear();
                    collected.addAll(event.citations());
                }
                sink.emit(
                        new ChatStreamFrame(
                                ChatStreamFrame.EVENT_RETRIEVAL,
                                new ChatStreamFrame.Retrieval(
                                        citationMapper.toVOs(event.citations()))));
            }
            case ChatStreamFrame.EVENT_TOKEN -> {
                if (event.content() != null) {
                    answer.append(event.content());
                    sink.emit(
                            new ChatStreamFrame(
                                    ChatStreamFrame.EVENT_TOKEN,
                                    new ChatStreamFrame.Token(event.content())));
                }
            }
            case ChatStreamFrame.EVENT_DONE -> {
                long elapsed =
                        event.elapsedMs() != null
                                ? event.elapsedMs()
                                : System.currentTimeMillis() - startedAt;
                persistAndFinish(
                        context,
                        sink,
                        answer.toString(),
                        new ArrayList<>(collected),
                        event,
                        elapsed,
                        Boolean.TRUE.equals(event.degraded()),
                        terminated);
            }
            case ChatStreamFrame.EVENT_ERROR -> {
                // 手册 §7 第 ④ 条：AI 侧报错也走降级，前端凭 done.degraded 判断，不用 error 帧打断体验。
                log.warn("AI 侧 error 事件 code={} message={}", event.code(), event.message());
                degrade(context, sink, answer, collected, startedAt, terminated);
            }
            default -> {
                // 未知事件一律透传原始 data（手册 §7：「保证 Python 加字段不炸 Java」）。
                log.debug("透传未知事件 {}", name);
                sink.emit(new ChatStreamFrame(name, event.raw() == null ? Map.of() : event.raw()));
            }
        }
    }

    /**
     * 异步落库并在完成后发终帧。
     *
     * @param context 上下文
     * @param sink 出口
     * @param content 累积正文
     * @param citations 累积引用（内部形状）
     * @param upstreamDone 上游 done 事件，可为 null（降级路径）
     * @param elapsedMs 耗时
     * @param degraded 是否降级
     * @param terminated 终态闸门：只有第一个到终态的事件会真正落库并结束流
     */
    private void persistAndFinish(
            ChatContext context,
            EventSink sink,
            String content,
            List<AiCitation> citations,
            AiStreamEvent upstreamDone,
            long elapsedMs,
            boolean degraded,
            AtomicBoolean terminated) {
        if (!terminated.compareAndSet(false, true)) {
            log.debug("终态已处理过，忽略重复的终态事件 conversationId={}", context.conversationId());
            return;
        }
        Map<String, Integer> usage =
                upstreamDone == null ? null : normalizeUsage(upstreamDone.usage());
        persistExecutor.execute(
                () -> {
                    Long assistantId = null;
                    try {
                        assistantId =
                                persistService.persistTurn(
                                        context, content, citations, usage, elapsedMs, degraded);
                    } catch (RuntimeException ex) {
                        log.error("落库失败 conversationId={}", context.conversationId(), ex);
                    }
                    emitDone(sink, upstreamDone, assistantId, usage, elapsedMs, degraded);
                    sink.complete();
                });
    }

    /**
     * 发 done 帧。
     *
     * <p>{@code messageId} 优先用数据库 id：前端会拿它去拉 trace，用 Python 的字符串 id 查不到。
     */
    private void emitDone(
            EventSink sink,
            AiStreamEvent upstreamDone,
            Long assistantId,
            Map<String, Integer> usage,
            long elapsedMs,
            boolean degraded) {
        List<String> suggestions =
                upstreamDone == null || upstreamDone.suggestions() == null
                        ? List.of()
                        : upstreamDone.suggestions().stream()
                                .limit(properties.getChat().getMaxSuggestions())
                                .toList();
        String messageId =
                assistantId != null
                        ? String.valueOf(assistantId)
                        : (upstreamDone == null ? null : upstreamDone.messageId());
        sink.emit(
                new ChatStreamFrame(
                        ChatStreamFrame.EVENT_DONE,
                        new ChatStreamFrame.Done(
                                messageId,
                                usage,
                                elapsedMs,
                                degraded,
                                suggestions,
                                upstreamDone == null ? null : upstreamDone.directMessageId(),
                                upstreamDone == null ? null : upstreamDone.directContent())));
    }

    /**
     * 把 usage 归一成契约要求的 {@code Map<String,Integer>}。
     *
     * <p>Python 可能给 {@code {"prompt_tokens": 812}} 或 {@code {"promptTokens": 812}}，也可能是浮点； 契约里
     * usage 是 {@code additionalProperties: {type: integer}}，非整数会被契约校验打掉。
     */
    private Map<String, Integer> normalizeUsage(Map<String, Object> raw) {
        if (raw == null || raw.isEmpty()) {
            return null;
        }
        Map<String, Integer> result = new LinkedHashMap<>();
        for (Map.Entry<String, Object> entry : raw.entrySet()) {
            if (entry.getValue() instanceof Number number) {
                result.put(entry.getKey(), number.intValue());
            }
        }
        return result.isEmpty() ? null : result;
    }

    /** 库里存的轨迹（Object）转强类型 VO，形状不对就返回 null 而不是 500。 */
    @SuppressWarnings("unchecked")
    private RetrievalTraceVO toTraceVO(Object raw) {
        if (!(raw instanceof Map<?, ?> map)) {
            return null;
        }
        Map<String, Object> data = (Map<String, Object>) map;
        List<TraceRowVO> rows = new ArrayList<>();
        if (data.get("rows") instanceof List<?> list) {
            for (Object item : list) {
                if (item instanceof Map<?, ?> row) {
                    Map<String, Object> r = (Map<String, Object>) row;
                    rows.add(
                            new TraceRowVO(
                                    asInt(r.get("rank"), rows.size() + 1),
                                    asString(r.get("chunkId")),
                                    asString(r.get("docId")),
                                    asString(r.get("docTitle")),
                                    asString(r.get("headingPath")),
                                    asString(r.get("text")),
                                    asInt(r.get("start"), 0),
                                    asInt(r.get("end"), 0),
                                    asDouble(r.get("score")),
                                    Boolean.TRUE.equals(r.get("retrieved")),
                                    asString(r.get("kind")),
                                    !Boolean.FALSE.equals(r.get("verified"))));
                }
            }
        }
        if (rows.isEmpty()) {
            return null;
        }
        return new RetrievalTraceVO(
                asString(data.get("question")),
                asInt(data.get("k"), DEFAULT_K),
                asInt(data.get("chunkSize"), 180),
                asInt(data.get("overlap"), 30),
                rows);
    }

    private int asInt(Object value, int fallback) {
        return value instanceof Number number ? number.intValue() : fallback;
    }

    private double asDouble(Object value) {
        return value instanceof Number number ? number.doubleValue() : 0.0d;
    }

    private String asString(Object value) {
        return value == null ? "" : String.valueOf(value);
    }

    /**
     * 归一化 mode：null/空按 rag；非法值抛 40001。
     *
     * <p>{@code ChatRequest} 上的 {@code @Pattern} 已在 Controller 层挡了一道，这里再挡是为了让 Service
     * 被单独调用（测试、未来的内部调用）时行为一致。
     */
    private String normalizeMode(String mode) {
        if (mode == null || mode.isBlank()) {
            return DEFAULT_MODE;
        }
        String normalized = mode.trim();
        if (!MODES.contains(normalized)) {
            throw new ApiException(
                    ErrorCode.INVALID_PARAM.getCode(), "mode 只能是 rag / direct / both");
        }
        return normalized;
    }

    /** 归一化 k：null 按 3；越界抛 40001。 */
    private int normalizeK(Integer k) {
        if (k == null) {
            return DEFAULT_K;
        }
        if (k < MIN_K || k > MAX_K) {
            throw new ApiException(
                    ErrorCode.INVALID_PARAM.getCode(), "k 需在 " + MIN_K + "-" + MAX_K + " 之间");
        }
        return k;
    }

    /** 取会话；不存在抛 40406。入参 conversationId 为 null 时新建一个。 */
    private Conversation resolveConversation(Long userId, Long conversationId, String question) {
        if (conversationId == null) {
            Conversation created = new Conversation();
            created.setUserId(userId);
            created.setTitle(titleOf(question));
            return conversationRepository.save(created);
        }
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
            throw new ApiException(
                    ErrorCode.CONVERSATION_NOT_FOUND.getCode(),
                    ErrorCode.CONVERSATION_NOT_FOUND.getDefaultMessage());
        }
        return conversation;
    }

    /**
     * 取最近 N 轮历史（一轮 = 用户 + 助手各一条）。
     *
     * <p>倒序取 {@code N*2} 条再反转：直接升序取会拿到最早的消息，正好相反。
     */
    private List<HistoryTurn> loadHistory(Long conversationId) {
        int turns = Math.max(1, properties.getChat().getHistoryTurns());
        List<Message> recent =
                messageRepository.findByConversationIdAndDeletedFalseOrderByCreatedAtDescIdDesc(
                        conversationId, PageRequest.of(0, turns * 2));
        if (recent.isEmpty()) {
            return List.of();
        }
        List<Message> ordered = new ArrayList<>(recent);
        Collections.reverse(ordered);
        List<HistoryTurn> history = new ArrayList<>(ordered.size());
        for (Message message : ordered) {
            history.add(new HistoryTurn(message.getRole(), message.getContent()));
        }
        return history;
    }

    private String titleOf(String question) {
        if (question == null || question.isBlank()) {
            return DEFAULT_TITLE;
        }
        String trimmed = question.trim();
        return trimmed.length() <= TITLE_MAX ? trimmed : trimmed.substring(0, TITLE_MAX);
    }
}
