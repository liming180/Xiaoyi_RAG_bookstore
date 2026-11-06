package com.xiaoyi.rag.client;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.xiaoyi.rag.client.dto.AiChatRequest;
import com.xiaoyi.rag.client.dto.AiChunk;
import com.xiaoyi.rag.client.dto.AiCitation;
import com.xiaoyi.rag.client.dto.AiIndexManifest;
import com.xiaoyi.rag.client.dto.AiIngestTask;
import com.xiaoyi.rag.client.dto.AiParseRequest;
import com.xiaoyi.rag.client.dto.AiParseResult;
import com.xiaoyi.rag.client.dto.AiStreamEvent;
import com.xiaoyi.rag.config.XiaoyiProperties;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.stream.Stream;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

/**
 * Java 到 Python 的内部 HTTP/SSE 客户端，{@code xiaoyi.ai.mock=false} 时生效。
 *
 * <p>H2：所有用户态调用都带 {@code X-User-Id}，Python 侧据此限定检索、入库、状态与文档的可见范围。 用户标识只来自已验签的 Java 会话，绝不取自请求体或前端头。
 *
 * <p>H3：{@link #chatStream} 返回可取消句柄，浏览器断开后真正停掉上游，而不是继续读一条没人要的流。
 */
@Component
@ConditionalOnProperty(name = "xiaoyi.ai.mock", havingValue = "false")
public class RealAiServiceClient implements AiServiceClient {

    private static final int MAX_STATUS_ATTEMPTS = 3;

    private static final long CIRCUIT_OPEN_MS = 10_000L;

    private static final int CIRCUIT_THRESHOLD = 3;

    /** 用户标识头，与 Python 侧 {@code X-User-Id} 对齐。 */
    private static final String USER_HEADER = "X-User-Id";

    private final ObjectMapper mapper;

    private final ObjectMapper snakeMapper;

    private final XiaoyiProperties properties;

    private final HttpClient http;

    private final AtomicInteger chatFailures = new AtomicInteger();

    private final AtomicLong chatOpenedAt = new AtomicLong();

    public RealAiServiceClient(ObjectMapper mapper, XiaoyiProperties properties) {
        this.mapper = mapper;
        this.snakeMapper =
                mapper.copy().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
        this.properties = properties;
        // 必须钉住 HTTP/1.1：JDK HttpClient 默认先发 h2c 升级（Connection: Upgrade, HTTP2-Settings），
        // uvicorn 的 h11 实现直接回 400 "Invalid HTTP request received."，Java 侧再翻成 50301，
        // 表现为「AI 服务不可用」而 Python 日志里只有一句 Unsupported upgrade request。
        this.http =
                HttpClient.newBuilder()
                        .version(HttpClient.Version.HTTP_1_1)
                        .connectTimeout(Duration.ofMillis(properties.getAi().getConnectTimeoutMs()))
                        .build();
    }

    @Override
    public StreamHandle chatStream(Long userId, AiChatRequest request, StreamListener listener) {
        if (circuitOpen()) {
            throw new IllegalStateException("Python AI chat circuit is open");
        }
        HttpRequest httpRequest =
                jsonRequest(
                        userId,
                        "/internal/v1/chat/stream",
                        request,
                        properties.getAi().getReadTimeoutMs());
        AtomicBoolean cancelled = new AtomicBoolean(false);
        CompletableFuture<HttpResponse<Stream<String>>> future =
                http.sendAsync(httpRequest, HttpResponse.BodyHandlers.ofLines());
        future.whenComplete(
                (response, error) -> {
                    if (cancelled.get()) {
                        // 客户端已经走了：不再回调，也不再计入熔断计数，否则正常的中断会误开熔断。
                        closeQuietly(response);
                        return;
                    }
                    if (error != null) {
                        recordChatFailure();
                        listener.onError(unwrap(error));
                        return;
                    }
                    if (response.statusCode() / 100 != 2) {
                        closeQuietly(response);
                        recordChatFailure();
                        listener.onError(
                                new IllegalStateException(
                                        "Python chat HTTP " + response.statusCode()));
                        return;
                    }
                    try {
                        parseSse(response, listener, cancelled);
                        chatFailures.set(0);
                        chatOpenedAt.set(0);
                    } catch (RuntimeException ex) {
                        if (!cancelled.get()) {
                            recordChatFailure();
                            listener.onError(ex);
                        }
                    }
                });
        return () -> {
            if (cancelled.compareAndSet(false, true)) {
                // 取消 future 会关掉底层连接，Python 侧随之停止生成。
                future.cancel(true);
            }
        };
    }

    @Override
    public AiParseResult parseDocuments(Long userId, AiParseRequest request) {
        JsonNode data =
                postIdempotent(
                        userId,
                        "/internal/v1/documents/parse",
                        request,
                        properties.getAi().getIngestSubmitTimeoutMs());
        return convert(data, AiParseResult.class);
    }

    @Override
    public AiIngestTask getIngestTask(Long userId, String taskId) {
        JsonNode data = getWithRetry(userId, "/internal/v1/ingest/" + encode(taskId));
        return convertIngest(data);
    }

    @Override
    public AiIndexManifest getIndexManifest(Long userId) {
        JsonNode data = getWithRetry(userId, "/internal/v1/index/status");
        return convert(data, AiIndexManifest.class);
    }

    /** J6 内部检索调用；返回整棵树，保留完整 trace 载荷。 */
    @Override
    public JsonNode retrieve(Long userId, Map<String, Object> request) {
        return call(
                userId,
                "POST",
                "/internal/v1/retrieve",
                request,
                properties.getAi().getReadTimeoutMs());
    }

    /** J6 内部批量评测调用；返回整棵树，保留 Python 的批结果形状。 */
    @Override
    public JsonNode evalBatch(Long userId, Map<String, Object> request) {
        return call(
                userId,
                "POST",
                "/internal/v1/eval/batch",
                request,
                properties.getAi().getReadTimeoutMs());
    }

    /** J6 单资料状态查询。路径与 Python 侧 {@code GET /internal/v1/documents/{id}/status} 对齐。 */
    @Override
    public JsonNode getDocumentStatus(Long userId, String documentId) {
        return getWithRetry(userId, "/internal/v1/documents/" + encode(documentId) + "/status");
    }

    /** J6 内部健康检查；进程级探活，不带用户。 */
    @Override
    public JsonNode health() {
        return getWithRetry(null, "/internal/v1/health");
    }

    private JsonNode getWithRetry(Long userId, String path) {
        RuntimeException last = null;
        for (int attempt = 1; attempt <= MAX_STATUS_ATTEMPTS; attempt++) {
            try {
                return call(userId, "GET", path, null, properties.getAi().getStatusTimeoutMs());
            } catch (NonRetryableAiException ex) {
                throw ex;
            } catch (RuntimeException ex) {
                last = ex;
                if (attempt < MAX_STATUS_ATTEMPTS) {
                    sleep(100L << (attempt - 1));
                }
            }
        }
        throw last;
    }

    /**
     * 幂等 POST：网络层失败（连接被重置、空闲连接被对端回收、读超时）时重试同一次提交。
     *
     * <p>为什么只对 {@code /internal/v1/documents/parse} 这么做：它是唯一由 Python 侧按 {@code (user_id,
     * submission_key)} 去重写接口。Java 把任务自带的 {@code submission_key} 原样重发，Python 返回的是同一个 {@code
     * task_id}， 不会重复切片段；而其它 POST（检索、评测）没有幂等键，重放会真的多做一次计算。
     *
     * <p>真实触发场景：Keep-Alive 连接在 Python 侧被回收后，JDK HttpClient 仍复用它，第一次写请求体就拿到 {@code IOException:
     * Connection reset}。旧实现直接把它翻成 50301「AI 服务不可用」，用户点一次重建就失败， 再点一次又好 —— 表现为随机 503。
     *
     * <p>4xx 不重试（{@link NonRetryableAiException}）：那是请求本身不合法，重放只会重复同一个错误。
     */
    private JsonNode postIdempotent(Long userId, String path, Object body, int timeoutMs) {
        RuntimeException last = null;
        for (int attempt = 1; attempt <= MAX_STATUS_ATTEMPTS; attempt++) {
            try {
                return call(userId, "POST", path, body, timeoutMs);
            } catch (NonRetryableAiException ex) {
                throw ex;
            } catch (RuntimeException ex) {
                last = ex;
                if (attempt < MAX_STATUS_ATTEMPTS) {
                    sleep(120L << (attempt - 1));
                }
            }
        }
        throw last;
    }

    private JsonNode call(Long userId, String method, String path, Object body, int timeoutMs) {
        HttpRequest.Builder builder =
                HttpRequest.newBuilder(uri(path))
                        .timeout(Duration.ofMillis(timeoutMs))
                        .header("X-Internal-Token", properties.getAi().getInternalToken())
                        .header("Accept", "application/json");
        if (userId != null) {
            builder.header(USER_HEADER, String.valueOf(userId));
        }
        try {
            if ("POST".equals(method)) {
                builder.header("Content-Type", "application/json")
                        .POST(
                                HttpRequest.BodyPublishers.ofString(
                                        snakeMapper.writeValueAsString(body)));
            } else {
                builder.GET();
            }
            HttpResponse<String> response =
                    http.send(builder.build(), HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() / 100 != 2) {
                int status = response.statusCode();
                if (status >= 400 && status < 500) {
                    throw new NonRetryableAiException(
                            "Python AI HTTP " + status + ": " + response.body());
                }
                throw new IllegalStateException(
                        "Python AI HTTP " + status + ": " + response.body());
            }
            JsonNode root = mapper.readTree(response.body());
            if (root.has("code") && root.path("code").asInt(0) != 0) {
                throw new IllegalStateException("Python AI code " + root.path("code").asInt());
            }
            return root.has("data") ? root.get("data") : root;
        } catch (InterruptedException ex) {
            // 只有真的被中断才恢复中断位。原来把 IOException 也算进来，会让线程池里的线程带着
            // interrupt 标记回到池子，下一次拿到的任务会在第一个阻塞点莫名抛出。
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Python AI request interrupted: " + path, ex);
        } catch (IOException ex) {
            throw new IllegalStateException("Python AI request failed: " + path, ex);
        }
    }

    private void parseSse(
            HttpResponse<Stream<String>> response,
            StreamListener listener,
            AtomicBoolean cancelled) {
        String event = "message";
        StringBuilder data = new StringBuilder();
        try (Stream<String> lines = response.body()) {
            Iterator<String> iterator = lines.iterator();
            while (iterator.hasNext()) {
                if (cancelled.get()) {
                    return;
                }
                String line = iterator.next();
                if (line.startsWith("event:")) {
                    event = line.substring(6).trim();
                } else if (line.startsWith("data:")) {
                    data.append(line.substring(5).trim());
                } else if (line.isBlank() && data.length() > 0) {
                    emitSse(event, data.toString(), listener);
                    data.setLength(0);
                    event = "message";
                }
            }
        }
        if (data.length() > 0 && !cancelled.get()) {
            emitSse(event, data.toString(), listener);
        }
    }

    private void emitSse(String event, String json, StreamListener listener) {
        try {
            Map<String, Object> raw = mapper.readValue(json, new TypeReference<>() {});
            JsonNode node = mapper.valueToTree(raw);
            AiStreamEvent parsed =
                    switch (event) {
                        case "status" ->
                                new AiStreamEvent(
                                        event,
                                        node.path("stage").asText(null),
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        raw);
                        case "retrieval" ->
                                new AiStreamEvent(
                                        event,
                                        null,
                                        convertList(node.path("citations"), AiCitation.class),
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        raw);
                        case "token" ->
                                new AiStreamEvent(
                                        event,
                                        null,
                                        null,
                                        node.path("content").asText(null),
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        raw);
                        case "done" ->
                                new AiStreamEvent(
                                        event,
                                        null,
                                        null,
                                        null,
                                        node.path("message_id").asText(null),
                                        map(node.path("usage")),
                                        node.path("elapsed_ms").asLong(),
                                        node.path("degraded").asBoolean(false),
                                        list(node.path("suggestions")),
                                        node.path("direct_message_id").asText(null),
                                        node.path("direct_content").asText(null),
                                        null,
                                        null,
                                        null,
                                        raw);
                        case "error" ->
                                new AiStreamEvent(
                                        event,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        null,
                                        node.path("code").asInt(),
                                        node.path("message").asText(null),
                                        node.path("fallback").asText(null),
                                        raw);
                        default -> AiStreamEvent.unknown(event, raw);
                    };
            listener.onEvent(parsed);
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("Invalid Python SSE data", ex);
        }
    }

    private AiIngestTask convertIngest(JsonNode data) {
        return new AiIngestTask(
                data.path("task_id").asText(),
                data.path("status").asText(),
                data.path("stage").asText(),
                data.path("progress").asInt(),
                data.path("doc_count").asInt(),
                data.path("chunk_count").asInt(),
                data.path("error").asText(null),
                convertList(data.path("chunks"), AiChunk.class));
    }

    private <T> T convert(JsonNode data, Class<T> type) {
        return snakeMapper.convertValue(data, type);
    }

    private <T> List<T> convertList(JsonNode node, Class<T> type) {
        return node.isArray()
                ? snakeMapper.convertValue(
                        node, mapper.getTypeFactory().constructCollectionType(List.class, type))
                : List.of();
    }

    private Map<String, Object> map(JsonNode node) {
        return node.isObject() ? mapper.convertValue(node, new TypeReference<>() {}) : Map.of();
    }

    private List<String> list(JsonNode node) {
        return node.isArray() ? mapper.convertValue(node, new TypeReference<>() {}) : List.of();
    }

    private HttpRequest jsonRequest(Long userId, String path, Object body, int timeout) {
        try {
            HttpRequest.Builder builder =
                    HttpRequest.newBuilder(uri(path))
                            .timeout(Duration.ofMillis(timeout))
                            .header("X-Internal-Token", properties.getAi().getInternalToken())
                            .header("Accept", "text/event-stream")
                            .header("Content-Type", "application/json");
            if (userId != null) {
                builder.header(USER_HEADER, String.valueOf(userId));
            }
            return builder.POST(
                            HttpRequest.BodyPublishers.ofString(
                                    snakeMapper.writeValueAsString(body)))
                    .build();
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("Cannot encode Python AI request", ex);
        }
    }

    private URI uri(String path) {
        return URI.create(properties.getAi().getBaseUrl().replaceAll("/$", "") + path);
    }

    private String encode(String value) {
        return URI.create("http://localhost/" + value).getPath().substring(1);
    }

    private boolean circuitOpen() {
        long opened = chatOpenedAt.get();
        return opened > 0 && System.currentTimeMillis() - opened < CIRCUIT_OPEN_MS;
    }

    private void recordChatFailure() {
        if (chatFailures.incrementAndGet() >= CIRCUIT_THRESHOLD) {
            chatOpenedAt.compareAndSet(0, System.currentTimeMillis());
        }
    }

    private static void closeQuietly(HttpResponse<Stream<String>> response) {
        if (response == null || response.body() == null) {
            return;
        }
        try {
            response.body().close();
        } catch (RuntimeException ignored) {
            // 关流失败没有补救手段，也不该盖掉真正要上报的取消语义。
        }
    }

    private static final class NonRetryableAiException extends RuntimeException {
        private NonRetryableAiException(String message) {
            super(message);
        }
    }

    private static Throwable unwrap(Throwable error) {
        return error instanceof ExecutionException && error.getCause() != null
                ? error.getCause()
                : error;
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Retry interrupted", ex);
        }
    }
}
