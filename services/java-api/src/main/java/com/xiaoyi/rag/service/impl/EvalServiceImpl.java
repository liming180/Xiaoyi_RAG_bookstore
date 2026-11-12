package com.xiaoyi.rag.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.xiaoyi.rag.client.AiServiceClient;
import com.xiaoyi.rag.client.dto.AiChatRequest;
import com.xiaoyi.rag.client.dto.AiStreamEvent;
import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.model.dto.EvalBatchRequest;
import com.xiaoyi.rag.model.entity.EvalRun;
import com.xiaoyi.rag.model.vo.EvalCaseResultVO;
import com.xiaoyi.rag.model.vo.EvalQuestionVO;
import com.xiaoyi.rag.model.vo.EvalRunVO;
import com.xiaoyi.rag.repository.EvalRunRepository;
import com.xiaoyi.rag.service.EvalService;
import com.xiaoyi.rag.service.QuestionBankService;
import jakarta.annotation.PostConstruct;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import org.springframework.stereotype.Service;

/** 评测只编排独立 AI 请求；任务和完整结果以数据库为准。 */
@Service
public class EvalServiceImpl implements EvalService {
    private final AiServiceClient ai;
    private final EvalRunRepository repository;
    private final ObjectMapper mapper;
    private final QuestionBankService bank;

    public EvalServiceImpl(
            AiServiceClient ai,
            EvalRunRepository repository,
            ObjectMapper mapper,
            QuestionBankService bank) {
        this.ai = ai;
        this.repository = repository;
        this.mapper = mapper;
        this.bank = bank;
    }

    /**
     * 启动时崩溃恢复：跨全部用户扫描非终态批次。
     *
     * <p>这里没有请求上下文，也不知道残留行属于谁，所以刻意不过滤 user_id —— 重启后任何还挂在 PENDING/RUNNING 的批次都已经没有执行线程， 统一置 FAILED
     * 才不会让前端永远转圈。
     */
    @PostConstruct
    public void recoverInterrupted() {
        for (EvalRun row : repository.findByStatusIn(List.of("PENDING", "RUNNING"))) {
            row.setStatus("FAILED");
            row.setFinishedAt(now());
            repository.save(row);
        }
    }

    /**
     * 当前用户的题库（P5-08 起题库是用户数据，不再是全局共享的静态 CSV）。
     *
     * @param userId 归属用户
     * @return 该用户启用中的题目
     */
    @Override
    public List<EvalQuestionVO> questions(Long userId) {
        return bank.listEnabled(userId);
    }

    @Override
    public EvalRunVO start(Long userId, EvalBatchRequest request) {
        if (request == null || request.mode() == null || request.k() == null)
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "评测参数缺失");
        String mode = request.mode();
        int k = request.k();
        if (k < 1 || k > 10 || !List.of("both", "direct", "rag").contains(mode))
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "评测参数非法");
        List<EvalQuestionVO> selected = selectQuestions(userId, request);
        if (selected.isEmpty()) {
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "没有可评测的题目");
        }
        EvalRun row = new EvalRun();
        row.setUserId(userId);
        row.setMode(mode);
        row.setTopK(k);
        row.setQuestionCount(selected.size());
        row.setStatus("PENDING");
        row.setProgress(0);
        row.setCreatedAt(now());
        row = repository.saveAndFlush(row);
        EvalRunVO initial = toVO(row);
        Long id = row.getId();
        Long owner = userId;
        Thread.startVirtualThread(() -> execute(owner, id, List.copyOf(selected)));
        return initial;
    }

    /**
     * 按请求解析本次要测的题目（P5-08）。
     *
     * <p>两条路径：{@code questionIds} 非空走精确点选；否则按 {@code types} 筛选、{@code sample} 决定顺序、 {@code limit}
     * 决定题数。题库会随时增长，所以筛选始终在服务端做，前端不需要先拉全库再回传题号。
     *
     * @param userId 归属用户
     * @param request 评测请求
     * @return 去重后的题目列表，保持请求顺序或题库顺序
     */
    private List<EvalQuestionVO> selectQuestions(Long userId, EvalBatchRequest request) {
        List<EvalQuestionVO> enabled = bank.listEnabled(userId);
        List<String> ids = request.questionIds();
        if (ids != null && !ids.isEmpty()) {
            List<EvalQuestionVO> picked = new ArrayList<>();
            for (String raw : ids) {
                String id = raw == null ? "" : raw.strip();
                EvalQuestionVO question =
                        enabled.stream()
                                .filter(item -> item.id().equals(id))
                                .findFirst()
                                .orElseThrow(
                                        () ->
                                                new ApiException(
                                                        ErrorCode.INVALID_PARAM.getCode(),
                                                        "题目不存在: " + id));
                if (!picked.contains(question)) picked.add(question);
            }
            return List.copyOf(picked);
        }

        List<String> types = request.types();
        List<EvalQuestionVO> filtered =
                types == null || types.isEmpty()
                        ? new ArrayList<>(enabled)
                        : enabled.stream()
                                .filter(q -> types.contains(q.type()))
                                .collect(java.util.stream.Collectors.toCollection(ArrayList::new));

        if (Boolean.TRUE.equals(request.sample())) {
            java.util.Collections.shuffle(filtered);
        }

        Integer limit = request.limit();
        if (limit != null && limit > 0 && limit < filtered.size()) {
            return List.copyOf(filtered.subList(0, limit));
        }
        return List.copyOf(filtered);
    }

    private void execute(Long userId, Long id, List<EvalQuestionVO> selected) {
        EvalRun row = repository.findById(id).orElseThrow();
        List<EvalCaseResultVO> cases = new ArrayList<>();
        try {
            row.setStatus("RUNNING");
            repository.save(row);
            for (EvalQuestionVO q : selected) {
                cases.addAll(evaluate(userId, List.of(q), row.getTopK(), Map.of()));
                row.setProgress(cases.size() * 100 / selected.size());
                saveResults(row, cases);
            }
            row.setStatus("SUCCEEDED");
            row.setProgress(100);
            row.setFinishedAt(now());
            saveResults(row, cases);
        } catch (Exception error) {
            row.setStatus("FAILED");
            row.setFinishedAt(now());
            saveResults(row, cases);
        }
    }

    private void saveResults(EvalRun row, List<EvalCaseResultVO> cases) {
        Map<String, Integer> stats =
                Map.of(
                        "total",
                        cases.size(),
                        "passedDirect",
                        (int) cases.stream().filter(EvalCaseResultVO::directPassed).count(),
                        "passedRag",
                        (int) cases.stream().filter(EvalCaseResultVO::ragPassed).count());
        try {
            row.setSummaryJson(
                    mapper.writeValueAsString(
                            new EvalRunVO(
                                    String.valueOf(row.getId()),
                                    row.getCreatedAt(),
                                    row.getFinishedAt(),
                                    row.getStatus(),
                                    row.getProgress(),
                                    stats,
                                    row.getMode(),
                                    row.getTopK(),
                                    List.copyOf(cases))));
            row.setResultCsv(csv(cases));
            repository.saveAndFlush(row);
        } catch (Exception error) {
            throw new IllegalStateException("保存评测结果失败", error);
        }
    }

    @Override
    public List<EvalCaseResultVO> evaluate(
            Long userId, List<EvalQuestionVO> selected, int k, Map<String, Object> options) {
        List<EvalCaseResultVO> cases = new ArrayList<>();
        for (EvalQuestionVO q : selected) {
            long start = System.nanoTime();
            Answer direct = answer(userId, q.question(), "direct", k, options);
            Answer rag = answer(userId, q.question(), "rag", k, options);
            cases.add(
                    new EvalCaseResultVO(
                            q.id(),
                            q.type(),
                            q.question(),
                            direct.text(),
                            judge(direct.text(), q.keywords()),
                            rag.text(),
                            judge(rag.text(), q.keywords()),
                            rag.sources(),
                            (System.nanoTime() - start) / 1_000_000));
        }
        return cases;
    }

    private Answer answer(
            Long userId, String question, String mode, int k, Map<String, Object> options) {
        CompletableFuture<Answer> completion = new CompletableFuture<>();
        StringBuilder text = new StringBuilder();
        List<String> sources = new ArrayList<>();
        ai.chatStream(
                userId,
                new AiChatRequest(question, List.of(), mode, k, List.of(), chatOptions(options)),
                new AiServiceClient.StreamListener() {
                    @Override
                    public synchronized void onEvent(AiStreamEvent event) {
                        if (event == null || completion.isDone()) return;
                        if ("token".equals(event.event()) && event.content() != null)
                            text.append(event.content());
                        if ("retrieval".equals(event.event()) && event.citations() != null)
                            event.citations().forEach(c -> sources.add(c.chunkId()));
                        if ("error".equals(event.event()))
                            completion.completeExceptionally(new IllegalStateException("AI 评测流错误"));
                        if ("done".equals(event.event())) {
                            if (Boolean.TRUE.equals(event.degraded()))
                                completion.completeExceptionally(
                                        new IllegalStateException("AI 评测降级"));
                            else
                                completion.complete(
                                        new Answer(text.toString(), List.copyOf(sources)));
                        }
                    }

                    @Override
                    public void onError(Throwable error) {
                        completion.completeExceptionally(error);
                    }
                });
        try {
            return completion.get(60, TimeUnit.SECONDS);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("评测中断", error);
        } catch (Exception error) {
            completion.cancel(false);
            throw new IllegalStateException("AI 评测失败", error);
        }
    }

    private record Answer(String text, List<String> sources) {}

    /**
     * 把实验参数翻译成内部契约 {@code InternalChatRequest.options}。
     *
     * <p>为什么必须显式挑字段：{@code options} 是内部契约里唯一允许的自由对象，但 Python 侧 只认 `rerank` / `summary` /
     * `chunk_size` / `overlap` 四个键。把整份实验参数原样塞过去 （`chunkSize`、`k` 这些 camelCase 键）不会报错，只会被静默忽略 ——
     * 于是「参数实验」 又变回装饰。这里只放 Python 真读的键，且用 snake_case。
     *
     * <p>`chunk_size` / `overlap` 对本轮问答没有影响（片段是建库时切好的），传过去只是为了 让 Python 侧诊断日志能对上「这轮是在什么参数下跑的」。
     *
     * @param options 实验组参数；普通评测传空 Map
     * @return 内部契约的 options；没有可传项时返回空 Map
     */
    private static Map<String, Object> chatOptions(Map<String, Object> options) {
        if (options == null || options.isEmpty()) {
            return Map.of();
        }
        Map<String, Object> result = new LinkedHashMap<>();
        Object rerank = options.get("rerank");
        if (rerank instanceof Boolean flag) {
            result.put("rerank", flag);
        }
        Object summary = options.get("summary");
        if (summary instanceof Boolean flag) {
            result.put("summary", flag);
        }
        Object chunkSize = options.get("chunkSize");
        if (chunkSize instanceof Number number) {
            result.put("chunk_size", number.intValue());
        }
        Object overlap = options.get("overlap");
        if (overlap instanceof Number number) {
            result.put("overlap", number.intValue());
        }
        return result;
    }

    public static boolean judge(String answer, String keywords) {
        if (keywords == null || keywords.isEmpty()) return false;
        // 判分前抹掉两侧所有空白：真实 provider（glm-4-flash）习惯在中文与数字间加空格，
        // 输出「最多借 4 本」「借期 21 天」，而题库关键词写的是 `4本` / `21天`。
        // 不归一化就会把完全正确的答案判成未命中，passedRag 被系统性压低。
        // 必须与 Python 侧 `routes._judge` 的 `_squash` 保持一致，否则两端结论会打架。
        String normalized = squash(answer);
        for (String group : keywords.split("\\|", -1)) {
            boolean hit = false;
            for (String alternative : group.split("/", -1)) {
                String word = squash(alternative);
                if (!word.isEmpty() && normalized.contains(word)) hit = true;
            }
            if (!hit) return false;
        }
        return true;
    }

    /** 去掉所有空白字符（空格、全角空格、换行、制表符）；关键词本身不含空格。 */
    private static String squash(String text) {
        if (text == null) return "";
        StringBuilder builder = new StringBuilder(text.length());
        for (int i = 0; i < text.length(); i++) {
            char ch = text.charAt(i);
            if (!Character.isWhitespace(ch) && ch != '\u3000') builder.append(ch);
        }
        return builder.toString();
    }

    @Override
    public List<EvalRunVO> runs(Long userId) {
        return repository.findAllByUserIdOrderByCreatedAtDescIdDesc(userId).stream()
                .map(this::toVO)
                .toList();
    }

    /**
     * 单次评测详情。
     *
     * <p>别人的批次与不存在的 id 走同一个分支，统一 40403：返回 403 等于告诉调用方「这个 id 真的存在」， 那是比看不到内容更严重的泄露。
     */
    @Override
    public EvalRunVO run(Long userId, String id) {
        return toVO(
                repository
                        .findByIdAndUserId(parseId(id), userId)
                        .orElseThrow(
                                () ->
                                        new ApiException(
                                                ErrorCode.EVAL_RUN_NOT_FOUND.getCode(),
                                                ErrorCode.EVAL_RUN_NOT_FOUND.getDefaultMessage())));
    }

    /** 契约 id 是字符串；格式不符按「记录不存在」处理，不抛 NumberFormatException。 */
    private Long parseId(String id) {
        try {
            return Long.parseLong(id);
        } catch (NumberFormatException error) {
            throw new ApiException(
                    ErrorCode.EVAL_RUN_NOT_FOUND.getCode(),
                    ErrorCode.EVAL_RUN_NOT_FOUND.getDefaultMessage());
        }
    }

    private EvalRunVO toVO(EvalRun row) {
        List<EvalCaseResultVO> cases = List.of();
        Map<String, Integer> stats = null;
        if (row.getSummaryJson() != null) {
            try {
                EvalRunVO saved = mapper.readValue(row.getSummaryJson(), EvalRunVO.class);
                cases = saved.cases() == null ? List.of() : saved.cases();
                stats = saved.stats();
            } catch (Exception error) {
                throw new IllegalStateException("读取评测结果失败", error);
            }
        }
        return new EvalRunVO(
                String.valueOf(row.getId()),
                row.getCreatedAt(),
                row.getFinishedAt(),
                row.getStatus(),
                row.getProgress(),
                stats,
                row.getMode(),
                row.getTopK(),
                cases);
    }

    private String csv(List<EvalCaseResultVO> cases) {
        StringBuilder text =
                new StringBuilder("\ufeff题号,题型,问题,不查资料回答,不查资料初判,查资料回答,查资料初判,来源数,耗时(ms)\r\n");
        for (EvalCaseResultVO c : cases) {
            String type =
                    switch (c.type()) {
                        case "single" -> "单文档";
                        case "cross" -> "跨文档";
                        default -> "库外";
                    };
            List<String> values =
                    List.of(
                            c.questionId(),
                            type,
                            c.question(),
                            c.directAnswer(),
                            c.directPassed() ? "通过" : "未通过",
                            c.ragAnswer(),
                            c.ragPassed() ? "通过" : "未通过",
                            String.valueOf(c.ragSources().size()),
                            String.valueOf(c.elapsedMs()));
            text.append(
                            String.join(
                                    ",",
                                    values.stream()
                                            .map(value -> "\"" + value.replace("\"", "\"\"") + "\"")
                                            .toList()))
                    .append("\r\n");
        }
        return text.toString();
    }

    private long now() {
        return System.currentTimeMillis() / 1000;
    }
}
