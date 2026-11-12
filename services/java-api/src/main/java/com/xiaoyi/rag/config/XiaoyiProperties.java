package com.xiaoyi.rag.config;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 小忆自有配置绑定（前缀 {@code xiaoyi}）。
 *
 * <p>用 {@code @ConfigurationProperties} 而不是散落的 {@code @Value}： 列表字段可以直接绑 {@code a,b,c} 字符串，也能绑 YAML
 * 列表，两种写法都吃。
 */
@org.springframework.validation.annotation.Validated
@ConfigurationProperties(prefix = "xiaoyi")
public class XiaoyiProperties {

    private Cors cors = new Cors();
    @Valid private Ai ai = new Ai();
    @Valid private Auth auth = new Auth();

    public Auth getAuth() {
        return auth;
    }

    public void setAuth(Auth auth) {
        this.auth = auth;
    }

    public static class Auth {
        @NotBlank private String jwtSecret;
        @NotBlank private String issuer = "xiaoyi-rag";

        @Min(1)
        private long tokenTtlSeconds = 3600;

        private String bootstrapUsername;
        private String bootstrapPassword;
        private String secondaryBootstrapUsername;
        private String secondaryBootstrapPassword;

        public String getJwtSecret() {
            return jwtSecret;
        }

        public void setJwtSecret(String value) {
            jwtSecret = value;
        }

        public String getIssuer() {
            return issuer;
        }

        public void setIssuer(String value) {
            issuer = value;
        }

        public long getTokenTtlSeconds() {
            return tokenTtlSeconds;
        }

        public void setTokenTtlSeconds(long value) {
            tokenTtlSeconds = value;
        }

        public String getBootstrapUsername() {
            return bootstrapUsername;
        }

        public void setBootstrapUsername(String value) {
            bootstrapUsername = value;
        }

        public String getBootstrapPassword() {
            return bootstrapPassword;
        }

        public void setBootstrapPassword(String value) {
            bootstrapPassword = value;
        }

        public String getSecondaryBootstrapUsername() {
            return secondaryBootstrapUsername;
        }

        public void setSecondaryBootstrapUsername(String value) {
            secondaryBootstrapUsername = value;
        }

        public String getSecondaryBootstrapPassword() {
            return secondaryBootstrapPassword;
        }

        public void setSecondaryBootstrapPassword(String value) {
            secondaryBootstrapPassword = value;
        }
    }

    private Storage storage = new Storage();
    private Chat chat = new Chat();
    private Index index = new Index();

    public Cors getCors() {
        return cors;
    }

    public void setCors(Cors cors) {
        this.cors = cors;
    }

    public Ai getAi() {
        return ai;
    }

    public void setAi(Ai ai) {
        this.ai = ai;
    }

    public Storage getStorage() {
        return storage;
    }

    public void setStorage(Storage storage) {
        this.storage = storage;
    }

    public Chat getChat() {
        return chat;
    }

    public void setChat(Chat chat) {
        this.chat = chat;
    }

    public Index getIndex() {
        return index;
    }

    public void setIndex(Index index) {
        this.index = index;
    }

    /** 跨域白名单。 */
    public static class Cors {

        private List<String> allowedOrigins =
                new ArrayList<>(Arrays.asList("http://localhost:5173", "http://127.0.0.1:5173"));

        public List<String> getAllowedOrigins() {
            return allowedOrigins;
        }

        public void setAllowedOrigins(List<String> allowedOrigins) {
            this.allowedOrigins = allowedOrigins;
        }
    }

    /** Python AI 服务连接参数。J1 只用到 mock 开关。 */
    public static class Ai {

        private String baseUrl = "http://127.0.0.1:8000";
        @NotBlank private String internalToken;
        private int connectTimeoutMs = 5000;
        private int readTimeoutMs = 60000;
        private int ingestSubmitTimeoutMs = 10000;
        private int statusTimeoutMs = 5000;
        private boolean mock = true;

        /**
         * 让 mock 客户端直接抛异常，用来验降级路径（手册 §7「test_stream_degrade.py：把 Python 停掉（或让 MockAiClient 抛异常）」）。
         *
         * <p>为什么不靠真的停掉 Python：J3 阶段 Python 服务还不存在（A1 才建），要验降级只能靠这个开关。 启动参数 {@code
         * --xiaoyi.ai.fail-mode=true}。
         */
        private boolean failMode = false;

        public String getBaseUrl() {
            return baseUrl;
        }

        public void setBaseUrl(String baseUrl) {
            this.baseUrl = baseUrl;
        }

        public String getInternalToken() {
            return internalToken;
        }

        public void setInternalToken(String internalToken) {
            this.internalToken = internalToken;
        }

        public int getConnectTimeoutMs() {
            return connectTimeoutMs;
        }

        public void setConnectTimeoutMs(int connectTimeoutMs) {
            this.connectTimeoutMs = connectTimeoutMs;
        }

        public int getReadTimeoutMs() {
            return readTimeoutMs;
        }

        public void setReadTimeoutMs(int readTimeoutMs) {
            this.readTimeoutMs = readTimeoutMs;
        }

        public int getIngestSubmitTimeoutMs() {
            return ingestSubmitTimeoutMs;
        }

        public void setIngestSubmitTimeoutMs(int ingestSubmitTimeoutMs) {
            this.ingestSubmitTimeoutMs = ingestSubmitTimeoutMs;
        }

        public int getStatusTimeoutMs() {
            return statusTimeoutMs;
        }

        public void setStatusTimeoutMs(int statusTimeoutMs) {
            this.statusTimeoutMs = statusTimeoutMs;
        }

        public boolean isMock() {
            return mock;
        }

        public void setMock(boolean mock) {
            this.mock = mock;
        }

        public boolean isFailMode() {
            return failMode;
        }

        public void setFailMode(boolean failMode) {
            this.failMode = failMode;
        }
    }

    /** 文件落盘根目录。 */
    public static class Storage {

        private String root = "./storage";

        public String getRoot() {
            return root;
        }

        public void setRoot(String root) {
            this.root = root;
        }
    }

    /** 问答编排参数。 */
    public static class Chat {

        /** 拼进 Python 请求的最近对话轮数（一轮 = 用户 + 助手各一条）。 */
        private int historyTurns = 5;

        /** 追问建议条数上限，与契约 done.suggestions 的展示位一致。 */
        private int maxSuggestions = 3;

        public int getHistoryTurns() {
            return historyTurns;
        }

        public void setHistoryTurns(int historyTurns) {
            this.historyTurns = historyTurns;
        }

        public int getMaxSuggestions() {
            return maxSuggestions;
        }

        public void setMaxSuggestions(int maxSuggestions) {
            this.maxSuggestions = maxSuggestions;
        }
    }

    /** 建库编排参数。 */
    public static class Index {

        /** 默认片段长度。与契约 chunkSize 的 50..1000 区间一致，取语料的自然段落量级。 */
        private int defaultChunkSize = 180;

        /** 默认重叠字数，必须小于 chunkSize。 */
        private int defaultOverlap = 30;

        /** embedding 模型名，写进 manifest 供 /index/status 展示。 */
        private String embeddingModel = "mock-embedding";

        /** 轮询入库任务的固定间隔（毫秒）。 */
        private long pollIntervalMs = 1000L;

        public int getDefaultChunkSize() {
            return defaultChunkSize;
        }

        public void setDefaultChunkSize(int defaultChunkSize) {
            this.defaultChunkSize = defaultChunkSize;
        }

        public int getDefaultOverlap() {
            return defaultOverlap;
        }

        public void setDefaultOverlap(int defaultOverlap) {
            this.defaultOverlap = defaultOverlap;
        }

        public String getEmbeddingModel() {
            return embeddingModel;
        }

        public void setEmbeddingModel(String embeddingModel) {
            this.embeddingModel = embeddingModel;
        }

        public long getPollIntervalMs() {
            return pollIntervalMs;
        }

        public void setPollIntervalMs(long pollIntervalMs) {
            this.pollIntervalMs = pollIntervalMs;
        }
    }
}
