package com.xiaoyi.rag.client;

import com.xiaoyi.rag.client.dto.AiChatRequest;
import com.xiaoyi.rag.client.dto.AiChunk;
import com.xiaoyi.rag.client.dto.AiCitation;
import com.xiaoyi.rag.client.dto.AiIndexManifest;
import com.xiaoyi.rag.client.dto.AiIngestTask;
import com.xiaoyi.rag.client.dto.AiParseDocumentItem;
import com.xiaoyi.rag.client.dto.AiParseRequest;
import com.xiaoyi.rag.client.dto.AiParseResult;
import com.xiaoyi.rag.client.dto.AiStreamEvent;
import com.xiaoyi.rag.config.XiaoyiProperties;
import jakarta.annotation.PreDestroy;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
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
 *
 * <p>J4 增加了入库三方法。入库进度**按轮询次数推进**而不是按墙钟时间：轮询周期是 1s，按时间推进时阶段窗口 与轮询节拍不对齐就会整段跳过，测试断言「五个 stage
 * 都出现过」会随机失败。 按次数推进则每次轮询必然前进一格，五个阶段一定被观察到。
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

    /**
     * 入库任务里带这个标记时，{@link #getIngestTask} 抛异常，用来验「轮询失败只重试、连续 30 次才 FAILED」。
     *
     * <p>和 {@link #FAIL_MARKER} 同样的理由：J4 阶段 Python 还不存在，只能靠 mock 主动失败。
     */
    public static final String POLL_FAIL_MARKER = "[pollfail]";

    private static final List<String> TOKENS =
            List.of("资料显示，", "读书会通常在", "每周六 14:00", "至 16:00 举行，", "地点在社区文化中心二层。");

    /**
     * 追问推荐模板（N2）：`{head}` 用问题前 8 个字填充。
     *
     * <p>与 `server-ai/app/services/suggestions.py` 的 `_MOCK_TEMPLATES` **逐字一致**。两边必须同步改 —— mock
     * 比真实后端宽松或更严，都会让门禁在 mock 档全绿、真实档全挂（反模式清单第 3 条）。
     *
     * <p>为什么不用固定一句「可以继续了解吗？」：常量永远等于常量，「推荐是否真的生成」这件事 就无法被门禁验证。J3 的用例断言「两个不同问题的推荐不完全相同」，靠的就是这里随问题变化。
     */
    private static final List<String> SUGGESTION_TEMPLATES =
            List.of("{head}还有哪些规定？", "{head}有例外情况吗？", "{head}具体怎么操作？");

    /** 追问推荐的条数上限，与 `xiaoyi.chat.max-suggestions` 默认值一致。 */
    private static final int MAX_SUGGESTIONS = 3;

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

    /** 建库阶段推进表：创建时是 parsing/0，之后每次轮询前进一格，第 4 次到 done/100。 */
    private static final String[] INGEST_STAGES = {"splitting", "embedding", "summarizing", "done"};

    private static final int[] INGEST_PROGRESS = {25, 50, 75, 100};

    private final ScheduledExecutorService scheduler =
            Executors.newSingleThreadScheduledExecutor(
                    r -> {
                        Thread thread = new Thread(r, "mock-ai-client");
                        thread.setDaemon(true);
                        return thread;
                    });

    private final AtomicInteger sequence = new AtomicInteger();

    private final AtomicInteger ingestSequence = new AtomicInteger();

    /** 已登记的入库任务：taskId → 状态。任务自带 userId，跨用户查询按不存在处理。 */
    private final Map<String, MockIngest> ingests = new ConcurrentHashMap<>();

    /**
     * 幂等索引：{@code userId + "\u0000" + submissionKey} → taskId。
     *
     * <p>H3 要求「同一个用户用同一个 submissionKey 重试，必须拿到同一个任务」。mock 里没有数据库， 就用这张表模拟 Python 侧的唯一约束。
     */
    private final Map<String, String> submissionIndex = new ConcurrentHashMap<>();

    private final XiaoyiProperties properties;

    public MockAiClient(XiaoyiProperties properties) {
        this.properties = properties;
    }

    @Override
    public StreamHandle chatStream(Long userId, AiChatRequest request, StreamListener listener) {
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
        List<AiCitation> citations = pickCitations(topK, rerankEffective(request));

        // 参数实验不模拟人的逐字阅读延迟，仍完整异步发出所有协议事件。
        long stepDelay =
                request != null && request.options() != null && !request.options().isEmpty()
                        ? 1L
                        : STEP_MS;
        List<Runnable> script = new ArrayList<>();
        script.add(() -> listener.onEvent(AiStreamEvent.status("rewriting")));
        script.add(() -> listener.onEvent(AiStreamEvent.status("retrieving")));
        script.add(() -> listener.onEvent(AiStreamEvent.status("reranking")));
        if (!"direct".equals(mode)) {
            script.add(() -> listener.onEvent(AiStreamEvent.retrieval(citations)));
        }
        script.add(() -> listener.onEvent(AiStreamEvent.status("generating")));
        List<String> answerTokens = mockAnswer(request, mode);
        for (String token : answerTokens) {
            script.add(() -> listener.onEvent(AiStreamEvent.token(token)));
        }
        // both 模式的「直接答」侧。刻意与 rag 侧措辞不同：对照模式的价值就在于两栏
        // 看得出差别，若 mock 两侧都吐通用套话，前端差异摘要条永远是 0 vs 0，
        // 连「摘要条有没有接上数据」都测不出来。
        // 真实 AI 侧（server-ai）由 provider 独立生成，这里只是 Java 的 mock 通道。

        // N2：推荐随问题变化，且 direct 模式不给（与 Python 侧 `suggestions.generate`
        // 在 direct 时无从推断追问的语义一致 —— 没有检索资料就没有「有据可答」的追问）。
        List<String> suggestions = "direct".equals(mode) ? List.of() : mockSuggestions(request);
        script.add(
                () -> {
                    Map<String, Object> usage = new LinkedHashMap<>();
                    usage.put("promptTokens", 128);
                    usage.put("completionTokens", TOKENS.size() * 6);
                    listener.onEvent(
                            AiStreamEvent.done(
                                    messageId,
                                    usage,
                                    stepDelay * script.size(),
                                    false,
                                    suggestions,
                                    "both".equals(mode) ? "m-direct-" + sequence.get() : null,
                                    "both".equals(mode) ? mockDirectAnswer(request) : null));
                    log.debug("MockAiClient 推完一轮事件 mode={} k={}", mode, topK);
                });

        // H3：浏览器断开后必须能停掉「上游」。mock 的上游就是这些排期任务，取消掉就不再往外推事件，
        // 与真实客户端关掉 HTTP 流的效果一致，ChatServiceImpl 的取消路径才能被测试覆盖。
        AtomicBoolean cancelled = new AtomicBoolean();
        List<ScheduledFuture<?>> futures = new ArrayList<>(script.size());
        long delay = FIRST_DELAY_MS;
        for (Runnable step : script) {
            futures.add(
                    scheduler.schedule(
                            () -> {
                                if (cancelled.get()) {
                                    return;
                                }
                                step.run();
                            },
                            delay,
                            TimeUnit.MILLISECONDS));
            delay += stepDelay;
        }
        return () -> {
            if (cancelled.compareAndSet(false, true)) {
                for (ScheduledFuture<?> future : futures) {
                    future.cancel(false);
                }
            }
        };
    }

    /**
     * mock 追问推荐：按问题前 8 个字套模板。
     *
     * <p>与 `server-ai/app/services/suggestions.py` 的 `mock_suggestions()` 同一套规则 —— 去句末标点、取前 8
     * 字、套三条模板、每条截到 20 字、去重、去掉与原问题相同的项。 两边不一致的话，「mock 档通过、真实档挂」就是迟早的事。
     *
     * @param request 内部契约请求，可为 null
     * @return 追问列表；问题为空时返回空列表
     */
    /**
     * both 模式下「直接答」侧的模拟回答。
     *
     * <p>刻意与 rag 侧措辞明显不同：对照模式的价值在于两栏看得出差别。若两侧都吐 通用套话，前端差异摘要条会永远显示「0 vs 0」，连摘要有没有接上数据都测不出来。
     *
     * <p>真实链路由 server-ai 的 provider 独立生成，这里只是 Java mock 通道： AI 服务不可达时降级使用的确定性回答。
     *
     * @param request 本轮请求，用来让答案随问题变化
     * @return 直答正文（不含任何 [n] 引用标记 —— 这个模式没有检索）
     */
    private static String mockDirectAnswer(AiChatRequest request) {
        String question = request == null ? "" : String.valueOf(request.question());
        if (question.contains("几本") || question.contains("借阅")) {
            return "按常见图书馆规则，普通图书一般一次可借 3 到 5 本，借期多为 30 天。" + "具体以你所在馆的规定为准 —— 我这里没有你们的借阅规则原文。";
        }
        if (question.contains("几点") || question.contains("时间")) {
            return "一般读书会安排在周末下午。不过各组织习惯不同，" + "具体时间建议看活动通知，我没有你们的日程表。";
        }
        if (question.contains("费用") || question.contains("多少钱")) {
            return "读书会多数是免费的，部分收取少量场地费。" + "你这个活动的收费标准我无从确认。";
        }
        return "这个问题我知道了方向，但缺少你们的具体资料，只能给出一般性说明。";
    }

    private static List<String> mockSuggestions(AiChatRequest request) {
        String question = request == null || request.question() == null ? "" : request.question();
        String stem = question.strip();
        while (!stem.isEmpty() && "？?。.！!～~ \t\r\n".indexOf(stem.charAt(stem.length() - 1)) >= 0) {
            stem = stem.substring(0, stem.length() - 1);
        }
        if (stem.isEmpty()) {
            return List.of();
        }
        String head = stem.length() <= 8 ? stem : stem.substring(0, 8);
        List<String> result = new ArrayList<>(MAX_SUGGESTIONS);
        for (String template : SUGGESTION_TEMPLATES) {
            String candidate = template.replace("{head}", head);
            if (candidate.length() > 20) {
                candidate = candidate.substring(0, 20);
            }
            if (!candidate.isEmpty()
                    && !candidate.equals(question)
                    && !result.contains(candidate)) {
                result.add(candidate);
            }
            if (result.size() >= MAX_SUGGESTIONS) {
                break;
            }
        }
        return List.copyOf(result);
    }

    /** 确定性联调答案；仅 mock provider 使用，不承担真实检索或生成逻辑。 */
    private List<String> mockAnswer(AiChatRequest request, String mode) {
        if ("direct".equals(mode)) {
            return List.of("（直答）读书会通常安排在周末，具体规则请向管理员确认。");
        }
        String question = request == null || request.question() == null ? "" : request.question();
        if (question.contains("费用") || question.contains("联系电话")) {
            return List.of("资料未提供该信息。");
        }
        if (question.contains("老成员")) {
            return List.of("不是，登记成员最多借4本普通图书，成员留言不构成正式规则。");
        }
        if (question.contains("2026年11月14日")) {
            return List.of("那一周调整为周日15:00开始，地点改为一层多功能厅。");
        }
        if (question.contains("期刊")) {
            return List.of("期刊最多同时借2本，借期7天。");
        }
        if (question.contains("截止时间") && question.contains("天数")) {
            return List.of("读书会报名截止周五18:00，空间预约可提前2天。");
        }
        if (question.contains("几点结束")) {
            return List.of("活动16:00结束，普通图书最多同时借4本。");
        }
        if (question.contains("取消")) {
            return List.of("至少提前30分钟取消预约。");
        }
        if (question.contains("讨论空间")) {
            return List.of("讨论空间需3至6人，每次最长2小时。");
        }
        if (question.contains("续借")) {
            return List.of("已经被别人预约的图书不能续借。");
        }
        if (question.contains("普通图书")) {
            return List.of("每人最多借4本普通图书，借期21天。");
        }
        if (question.contains("报名")) {
            return List.of("报名应于活动前一日周五18:00前完成。");
        }
        return TOKENS;
    }

    @Override
    public AiParseResult parseDocuments(Long userId, AiParseRequest request) {
        if (properties.getAi().isFailMode()) {
            throw new IllegalStateException("mock fail-mode：模拟 AI 服务不可达");
        }
        List<AiParseDocumentItem> documents =
                request == null || request.documents() == null ? List.of() : request.documents();
        int chunkSize = request == null || request.chunkSize() == null ? 180 : request.chunkSize();
        int overlap = request == null || request.overlap() == null ? 30 : request.overlap();
        String submissionKey = request == null ? null : request.submissionKey();

        // 幂等：同一用户、同一 submissionKey 的重试必须拿到同一个 task_id，
        // 与 Python 侧 (user_id, submission_key) 唯一约束语义一致。Java 侧触发超时后重放的就是同一次提交。
        if (submissionKey != null && !submissionKey.isBlank()) {
            String existing = submissionIndex.get(submissionIndexKey(userId, submissionKey));
            if (existing != null) {
                log.debug("MockAiClient 命中幂等键，复用入库任务 {}（用户 {}）", existing, userId);
                MockIngest known = ingests.get(existing);
                int knownDocs = known == null ? documents.size() : known.documents.size();
                return new AiParseResult(existing, knownDocs);
            }
        }

        String taskId = "mock-ingest-" + ingestSequence.incrementAndGet();
        MockIngest ingest =
                new MockIngest(
                        taskId,
                        userId,
                        documents,
                        chunkSize,
                        overlap,
                        request.genSummary() == null || request.genSummary());
        ingests.put(taskId, ingest);
        if (submissionKey != null && !submissionKey.isBlank()) {
            submissionIndex.putIfAbsent(submissionIndexKey(userId, submissionKey), taskId);
        }
        log.debug("MockAiClient 登记入库任务 {}，文档 {} 份", taskId, documents.size());
        return new AiParseResult(taskId, documents.size());
    }

    @Override
    public AiIngestTask getIngestTask(Long userId, String taskId) {
        if (properties.getAi().isFailMode()) {
            throw new IllegalStateException("mock fail-mode：模拟 AI 服务不可达");
        }
        MockIngest ingest = ingests.get(taskId);
        // 跨用户的任务按「不存在」处理：不区分「没有」和「不是你的」，避免任务 id 变成探测他人建库状态的侧信道。
        if (ingest == null || !ingest.userId.equals(userId)) {
            throw new IllegalStateException("mock 里没有入库任务：" + taskId);
        }
        if (ingest.pollFail) {
            throw new IllegalStateException("mock poll-fail-marker：模拟轮询失败");
        }

        int step = ingest.step.getAndIncrement();
        if (step >= INGEST_STAGES.length) {
            // 已经走完还被轮询：重复回同一个终态，别让计数无限涨。
            return ingest.finished();
        }
        String stage = INGEST_STAGES[step];
        int progress = INGEST_PROGRESS[step];
        boolean done = "done".equals(stage);
        if (done) {
            ingest.markFinished();
        }
        List<AiChunk> chunks = done ? ingest.chunks() : List.of();
        return new AiIngestTask(
                taskId,
                done ? "SUCCEEDED" : "RUNNING",
                stage,
                progress,
                ingest.documents.size(),
                done ? chunks.size() : 0,
                null,
                chunks);
    }

    @Override
    public AiIndexManifest getIndexManifest(Long userId) {
        if (properties.getAi().isFailMode()) {
            throw new IllegalStateException("mock fail-mode：模拟 AI 服务不可达");
        }
        MockIngest latest = null;
        for (MockIngest ingest : ingests.values()) {
            if (!ingest.userId.equals(userId)) {
                continue;
            }
            if (ingest.finishedAt != null
                    && (latest == null || ingest.finishedAt > latest.finishedAt)) {
                latest = ingest;
            }
        }
        if (latest == null) {
            return new AiIndexManifest("needs_rebuild", null, null, null, 0, 0, null, null, "尚未建库");
        }
        return new AiIndexManifest(
                "ready",
                "mock-embedding",
                latest.chunkSize,
                latest.overlap,
                latest.documents.size(),
                latest.chunks().size(),
                latest.finishedAt,
                null,
                null);
    }

    /**
     * 按 k 截断引用池，并按 1..n 重编 ref，模拟真实 RAG 的 top-k 编号。
     *
     * @param topK 召回条数
     * @param rerankEffective 本轮重排是否生效
     * @return 引用列表，至少一条
     */
    private List<AiCitation> pickCitations(int topK, boolean rerankEffective) {
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
                            // 重排关掉时引用档位退回融合顺序（rrf），与 Python 侧
                            // ingest.retrieve(rerank=False) 的行为一致 —— 否则 mock 档
                            // 的「rerank 轴真生效」用例会永远通过，等于没验。
                            rerankEffective ? source.scoreStage() : rrfStage(source.scoreStage()),
                            source.kind(),
                            source.verified()));
        }
        return picked;
    }

    /**
     * 把引用档位降级到融合阶段：`rerank` → `rrf`，其余原样。
     *
     * @param stage 原档位
     * @return 关掉重排后的档位
     */
    private static String rrfStage(String stage) {
        return "rerank".equals(stage) ? "rrf" : stage;
    }

    /**
     * 本轮重排是否生效：读 `options.rerank`，缺省 true（与全局 RETRIEVAL_RERANK 默认值一致）。
     *
     * @param request 内部契约请求
     * @return 生效则 true
     */
    private static boolean rerankEffective(AiChatRequest request) {
        if (request == null || request.options() == null) {
            return true;
        }
        Object value = request.options().get("rerank");
        return !(value instanceof Boolean flag) || flag;
    }

    /**
     * 幂等键的组合方式：用户与提交键之间用 NUL 分隔，避免两个不同用户各自使用 "a" / "b" 时拼出同一个键。
     *
     * @param userId 归属用户
     * @param submissionKey 提交幂等键
     * @return 组合后的 map 键
     */
    private static String submissionIndexKey(Long userId, String submissionKey) {
        return userId + "\u0000" + submissionKey;
    }

    @PreDestroy
    public void shutdown() {
        scheduler.shutdownNow();
    }

    /** 一个假入库任务的状态机。 */
    private static final class MockIngest {

        private final String taskId;

        /** 归属用户：所有读接口都先比对它，跨用户一律当「任务不存在」。 */
        private final Long userId;

        private final List<AiParseDocumentItem> documents;

        private final int chunkSize;

        private final int overlap;

        private final boolean pollFail;

        /** N3：本次建库是否生成摘要卡。false 时终态片段里没有 D00 系列。 */
        private final boolean genSummary;

        private final AtomicInteger step = new AtomicInteger();

        private volatile Long finishedAt;

        private volatile List<AiChunk> cached;

        private MockIngest(
                String taskId,
                Long userId,
                List<AiParseDocumentItem> documents,
                int chunkSize,
                int overlap,
                boolean genSummary) {
            this.taskId = taskId;
            this.userId = userId;
            this.documents = documents;
            this.chunkSize = chunkSize;
            this.overlap = overlap;
            this.genSummary = genSummary;
            this.pollFail =
                    documents.stream()
                            .anyMatch(
                                    d ->
                                            (d.name() != null
                                                            && d.name().contains(POLL_FAIL_MARKER))
                                                    || (d.text() != null
                                                            && d.text()
                                                                    .contains(POLL_FAIL_MARKER)));
        }

        private void markFinished() {
            if (finishedAt == null) {
                finishedAt = Instant.now().getEpochSecond();
            }
        }

        /** 终态回包：progress 恒 100、chunks 恒全量。 */
        private AiIngestTask finished() {
            List<AiChunk> chunks = chunks();
            return new AiIngestTask(
                    taskId,
                    "SUCCEEDED",
                    "done",
                    100,
                    documents.size(),
                    chunks.size(),
                    null,
                    chunks);
        }

        /**
         * 按 chunkSize / overlap 切片段，规则与真实实现一致：从 0 开始每次前进 {@code chunkSize - overlap}， 直到覆盖全文。
         *
         * <p>chunkId 用 {@code D{doc}-C{seq}}，doc 取资料的 id（1..99 内直接用，超了回落请求内序号）， 与对外契约 {@code
         * ^D\d{2}-C\d{3}$} 的模式一致。
         */
        private List<AiChunk> chunks() {
            List<AiChunk> cachedLocal = cached;
            if (cachedLocal != null) {
                return cachedLocal;
            }
            synchronized (this) {
                if (cached != null) {
                    return cached;
                }
                List<AiChunk> built = new ArrayList<>();
                int docSeq = 0;
                for (AiParseDocumentItem doc : documents) {
                    docSeq++;
                    int docNo = docSeq;
                    try {
                        int parsed = Integer.parseInt(doc.docId());
                        if (parsed >= 1 && parsed <= 99) {
                            docNo = parsed;
                        }
                    } catch (NumberFormatException ignored) {
                        // docId 不是数字就退回请求内序号
                    }
                    String text = doc.text() == null ? "" : doc.text();
                    int stride = Math.max(1, chunkSize - overlap);
                    int seq = 0;
                    for (int start = 0; start < text.length() && seq < 999; start += stride) {
                        int end = Math.min(text.length(), start + chunkSize);
                        seq++;
                        built.add(
                                new AiChunk(
                                        String.format("D%02d-C%03d", docNo, seq),
                                        doc.docId(),
                                        doc.title() == null ? doc.name() : doc.title(),
                                        "",
                                        text.substring(start, end),
                                        start,
                                        end,
                                        "chunk",
                                        true));
                        if (end >= text.length()) {
                            break;
                        }
                    }
                }
                // N3：摘要卡与普通片段同一批回传（Java 靠 data.chunks 落自己的 chunk 表）。
                built.addAll(summaryCards());
                cached = built;
                return built;
            }
        }

        /**
         * 摘要卡（N3）：统计卡 + 规则卡，编号固定 `D00-C001` / `D00-C002`。
         *
         * <p>与 Python 侧 `summarizer.mock_cards()` 的语义一致：统计卡说「共 N 份资料」， 规则卡挑含数字的条款句。这里不追求文字一致 ——
         * mock 的两端本来就各自造文档， 一致的是**形状与编号约定**（`D00-*`、`doc_id=__summary__`、`kind` 取值）。
         */
        private List<AiChunk> summaryCards() {
            if (!genSummary || documents.isEmpty()) {
                return List.of();
            }
            List<String> titles = new ArrayList<>(documents.size());
            for (AiParseDocumentItem doc : documents) {
                titles.add(doc.title() == null ? doc.name() : doc.title());
            }
            List<AiChunk> cards = new ArrayList<>(2);
            cards.add(
                    new AiChunk(
                            "D00-C001",
                            "__summary__",
                            "全库摘要",
                            "全库概览",
                            "全库共 " + documents.size() + " 份资料：" + String.join("、", titles) + "。",
                            0,
                            0,
                            "summary",
                            true));
            // 规则卡：挑第一条含数字的正文句子，形状与真实实现一致。
            for (AiParseDocumentItem doc : documents) {
                String text = doc.text() == null ? "" : doc.text();
                for (String raw : text.split("[。；;\\n]+")) {
                    String sentence = raw.strip();
                    if (!sentence.isEmpty() && sentence.chars().anyMatch(Character::isDigit)) {
                        cards.add(
                                new AiChunk(
                                        "D00-C002",
                                        "__summary__",
                                        "全库摘要",
                                        "借阅与资格规则",
                                        sentence + "。",
                                        0,
                                        sentence.length() + 1,
                                        "rule",
                                        true));
                        return cards;
                    }
                }
            }
            return cards;
        }
    }
}
