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
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

/** Java-to-Python internal HTTP/SSE client used when {@code xiaoyi.ai.mock=false}. */
@Component
@ConditionalOnProperty(name = "xiaoyi.ai.mock", havingValue = "false")
public class RealAiServiceClient implements AiServiceClient {

    private static final int MAX_STATUS_ATTEMPTS = 3;
    private static final long CIRCUIT_OPEN_MS = 10_000L;

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
        this.http =
                HttpClient.newBuilder()
                        .connectTimeout(Duration.ofMillis(properties.getAi().getConnectTimeoutMs()))
                        .build();
    }

    @Override
    public void chatStream(AiChatRequest request, StreamListener listener) {
        if (circuitOpen()) {
            throw new IllegalStateException("Python AI chat circuit is open");
        }
        HttpRequest httpRequest =
                jsonRequest(
                        "/internal/v1/chat/stream", request, properties.getAi().getReadTimeoutMs());
        http.sendAsync(httpRequest, HttpResponse.BodyHandlers.ofLines())
                .whenComplete(
                        (response, error) -> {
                            if (error != null) {
                                recordChatFailure();
                                listener.onError(unwrap(error));
                                return;
                            }
                            if (response.statusCode() / 100 != 2) {
                                recordChatFailure();
                                listener.onError(
                                        new IllegalStateException(
                                                "Python chat HTTP " + response.statusCode()));
                                return;
                            }
                            try {
                                parseSse(response, listener);
                                chatFailures.set(0);
                                chatOpenedAt.set(0);
                            } catch (RuntimeException ex) {
                                recordChatFailure();
                                listener.onError(ex);
                            }
                        });
    }

    @Override
    public AiParseResult parseDocuments(AiParseRequest request) {
        JsonNode data =
                call(
                        "POST",
                        "/internal/v1/documents/parse",
                        request,
                        properties.getAi().getIngestSubmitTimeoutMs());
        return convert(data, AiParseResult.class);
    }

    @Override
    public AiIngestTask getIngestTask(String taskId) {
        JsonNode data = getWithRetry("/internal/v1/ingest/" + encode(taskId));
        return convertIngest(data);
    }

    @Override
    public AiIndexManifest getIndexManifest() {
        JsonNode data = getWithRetry("/internal/v1/index/status");
        return convert(data, AiIndexManifest.class);
    }

    /** J6 internal retrieve call; returned tree keeps the complete trace payload. */
    public JsonNode retrieve(Map<String, Object> request) {
        return call(
                "POST", "/internal/v1/retrieve", request, properties.getAi().getReadTimeoutMs());
    }

    /** J6 internal evaluation call; returned tree keeps Python's batch result shape. */
    public JsonNode evalBatch(Map<String, Object> request) {
        return call(
                "POST", "/internal/v1/eval/batch", request, properties.getAi().getReadTimeoutMs());
    }

    /** J6 internal document status call. */
    public JsonNode getDocumentStatus(String documentId) {
        return getWithRetry("/internal/v1/documents/" + encode(documentId));
    }

    /** J6 internal health call. */
    public JsonNode health() {
        return getWithRetry("/internal/v1/health");
    }

    private JsonNode getWithRetry(String path) {
        RuntimeException last = null;
        for (int attempt = 1; attempt <= MAX_STATUS_ATTEMPTS; attempt++) {
            try {
                return call("GET", path, null, properties.getAi().getStatusTimeoutMs());
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

    private JsonNode call(String method, String path, Object body, int timeoutMs) {
        try {
            HttpRequest.Builder builder =
                    HttpRequest.newBuilder(uri(path))
                            .timeout(Duration.ofMillis(timeoutMs))
                            .header("X-Internal-Token", properties.getAi().getInternalToken())
                            .header("Accept", "application/json");
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
        } catch (IOException | InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Python AI request failed: " + path, ex);
        }
    }

    private void parseSse(
            HttpResponse<java.util.stream.Stream<String>> response, StreamListener listener) {
        String event = "message";
        StringBuilder data = new StringBuilder();
        try (java.util.stream.Stream<String> lines = response.body()) {
            java.util.Iterator<String> iterator = lines.iterator();
            while (iterator.hasNext()) {
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
        if (data.length() > 0) emitSse(event, data.toString(), listener);
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

    private HttpRequest jsonRequest(String path, Object body, int timeout) {
        return request(path, body, timeout);
    }

    private HttpRequest request(String path, Object body, int timeout) {
        try {
            return HttpRequest.newBuilder(uri(path))
                    .timeout(Duration.ofMillis(timeout))
                    .header("X-Internal-Token", properties.getAi().getInternalToken())
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body)))
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
        if (chatFailures.incrementAndGet() >= 3)
            chatOpenedAt.compareAndSet(0, System.currentTimeMillis());
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
