package com.xiaoyi.rag.client;

import com.xiaoyi.rag.client.dto.AiChatRequest;
import com.xiaoyi.rag.client.dto.AiCitation;
import com.xiaoyi.rag.client.dto.AiStreamEvent;
import com.xiaoyi.rag.config.XiaoyiProperties;
import jakarta.annotation.PreDestroy;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

/**
 * 假 AI 客户端：不连 Python，按固定节奏推 status → retrieval → token×5 → done。
 *
 * <p>存在意义是让 J3 之前前端就能联调 SSE；J6 换成真实 HTTP 客户端后本类靠 {@code xiaoyi.ai.mock=false} 自动下线。
 *
 * <p>三个刻意的设计：
 *
 * <ul>
 *   <li>引用不是空数组。J3 要验「trace 的行数与 retrieval 的 citations 条数一致」，空数组会让那条断言 退化成 {@code 0 ==
 *       0}，等于没验。这里给三条真实形状的引用（D02-C001 / D01-C001 / D05-C001）， 与 assets 里的语料对得上。
 *   <li>{@code mode=direct} 不发 retrieval 事件 —— 契约明写「direct 时不发」，前端靠这个区分两种模式。
 *   <li>{@code k} 会截断引用条数，这样 {@code k=1} 与 {@code k=3} 的 trace 行数不同，能验出参数真的生效。
 * </ul>
 */
@Component
@ConditionalOnProperty(name = "xiaoyi.ai.mock", havingValue = "true", matchIfMissing = true)
public class MockAiClient implements AiServiceClient {

    private static final Logger log = LoggerFactory.getLogger(MockAiClient.class);

    private static final long FIRST_DELAY_MS = 30L;
    private static final long STEP_MS = 60L;

    /**
     * 问题里带这个标记时，mock 直接抛异常，用来验降级路径。
     *
     * <p>为什么不用「停掉 Python」：J3 阶段 Python 服务还不存在（A1 才建），要验降级只能靠 mock 主动失败。 为什么不用「另起一个 fail-mode 实例」：J3
     * 的用例要能在**同一个**已起好的服务上跑完正常路径与降级路径， 两个实例会让 `pytest test/J3-sse` 依赖启动脚本传不同参数。 全局开关 {@code
     * xiaoyi.ai.fail-mode=true} 仍然保留，给门禁脚本做「整服务不可用」的整体验证。
     */
    public static final String FAIL_MARKER = "[fail]";

    private static final List<String> TOKENS =
            List.of("资料显示，", "读书会通常在", "每周六 14:00", "至 16:00 举行，", "地点在社区文化中心二层。");

    private static final List<String> SUGGESTIONS =
            List.of("报名最晚什么时候截止？", "普通图书一次能借几本？", "讨论空间需要提前多久预约？");

    /** 假引用池：形状与内部契约 InternalCitation 一致（snake_case 语义由字段顺序体现）。 */
    private static final List<AiCitation> CITATION_POOL =
            List.of(
                    new AiCitation(
                            1,
                            "D02-C001",
                            "2",
                            "02_借阅规则.md",
                            "# 星河读书会借阅规则 > ## 借阅上限",
                            "已登记成员每人最多同时借阅 4 本普通图书，每本借期 21 天。",
                            0,
                            40,
                            0.87d,
                            "rerank",
                            "chunk",
                            true),
                    new AiCitation(
                            2,
                            "D01-C001",
                            "1",
                            "01_活动说明.md",
                            "# 星河读书会活动说明 > ## 时间地点",
                            "读书会每周六 14:00 至 16:00 在社区文化中心二层举行。",
                            0,
                            38,
                            0.82d,
                            "rrf",
                            "chunk",
                            true),
                    new AiCitation(
                            3,
                            "D05-C001",
                            "5",
                            "05_活动调整通知.md",
                            "# 活动调整通知 > ## 十一月调整",
                            "2026 年 11 月 14 日那一周改为周日 15:00 至 17:00，地点改到一层多功能厅。",
                            0,
                            46,
                            0.74d,
                            "dense",
                            "rule",
                            false));

    private final ScheduledExecutorService scheduler =
            Executors.newSingleThreadScheduledExecutor(
                    r -> {
                        Thread thread = new Thread(r, "mock-ai-client");
                        thread.setDaemon(true);
                        return thread;
                    });

    private final AtomicInteger sequence = new AtomicInteger();

    private final XiaoyiProperties properties;

    public MockAiClient(XiaoyiProperties properties) {
        this.properties = properties;
    }

    @Override
    public void chatStream(AiChatRequest request, StreamListener listener) {
        if (properties.getAi().isFailMode()) {
            // 降级路径的验收入口：抛出去由 ChatServiceImpl 捕获，转 done{degraded:true}。
            throw new IllegalStateException("mock fail-mode：模拟 AI 服务不可达");
        }
        if (request != null
                && request.question() != null
                && request.question().contains(FAIL_MARKER)) {
            // 单请求级降级入口，见 FAIL_MARKER 的注释。
            throw new IllegalStateException("mock fail-marker：模拟 AI 服务不可达");
        }
        String mode = request == null || request.mode() == null ? "rag" : request.mode();
        int topK = request == null || request.k() == null ? 3 : request.k();
        String messageId = "m-" + sequence.incrementAndGet();
        List<AiCitation> citations = pickCitations(topK);

        List<Runnable> script = new ArrayList<>();
        script.add(() -> listener.onEvent(AiStreamEvent.status("rewriting")));
        script.add(() -> listener.onEvent(AiStreamEvent.status("retrieving")));
        script.add(() -> listener.onEvent(AiStreamEvent.status("reranking")));
        if (!"direct".equals(mode)) {
            script.add(() -> listener.onEvent(AiStreamEvent.retrieval(citations)));
        }
        script.add(() -> listener.onEvent(AiStreamEvent.status("generating")));
        for (String token : TOKENS) {
            script.add(() -> listener.onEvent(AiStreamEvent.token(token)));
        }
        script.add(
                () -> {
                    Map<String, Object> usage = new LinkedHashMap<>();
                    usage.put("promptTokens", 128);
                    usage.put("completionTokens", TOKENS.size() * 6);
                    listener.onEvent(
                            AiStreamEvent.done(
                                    messageId,
                                    usage,
                                    STEP_MS * script.size(),
                                    false,
                                    SUGGESTIONS,
                                    "both".equals(mode) ? "m-direct-" + sequence.get() : null,
                                    "both".equals(mode) ? "（直答）读书会每周六下午举行。" : null));
                    log.debug("MockAiClient 推完一轮事件 mode={} k={}", mode, topK);
                });

        long delay = FIRST_DELAY_MS;
        for (Runnable step : script) {
            scheduler.schedule(step, delay, TimeUnit.MILLISECONDS);
            delay += STEP_MS;
        }
    }

    /**
     * 按 k 截断引用池，并按 1..n 重编 ref，模拟真实 RAG 的 top-k 编号。
     *
     * @param topK 召回条数
     * @return 引用列表，至少一条
     */
    private List<AiCitation> pickCitations(int topK) {
        int limit = Math.max(1, Math.min(topK, CITATION_POOL.size()));
        List<AiCitation> picked = new ArrayList<>(limit);
        for (int i = 0; i < limit; i++) {
            AiCitation source = CITATION_POOL.get(i);
            picked.add(
                    new AiCitation(
                            i + 1,
                            source.chunkId(),
                            source.docId(),
                            source.docTitle(),
                            source.headingPath(),
                            source.excerpt(),
                            source.start(),
                            source.end(),
                            source.score(),
                            source.scoreStage(),
                            source.kind(),
                            source.verified()));
        }
        return picked;
    }

    @PreDestroy
    public void shutdown() {
        scheduler.shutdownNow();
    }
}
