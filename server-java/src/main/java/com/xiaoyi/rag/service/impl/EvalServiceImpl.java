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
import jakarta.annotation.PostConstruct;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
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
    private final List<EvalQuestionVO> questions;

    public EvalServiceImpl(AiServiceClient ai, EvalRunRepository repository, ObjectMapper mapper) {
        this.ai = ai;
        this.repository = repository;
        this.mapper = mapper;
        this.questions = loadQuestions();
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

    @Override
    public List<EvalQuestionVO> questions() {
        return questions;
    }

    @Override
    public EvalRunVO start(Long userId, EvalBatchRequest request) {
        if (request == null || request.mode() == null || request.k() == null)
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "评测参数缺失");
        String mode = request.mode();
        int k = request.k();
        if (k < 1 || k > 10 || !List.of("both", "direct", "rag").contains(mode))
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "评测参数非法");
        List<EvalQuestionVO> selected = new ArrayList<>();
        if (request.questionIds() == null || request.questionIds().isEmpty())
            selected.addAll(questions);
        else
            for (String id : request.questionIds()) {
                EvalQuestionVO q =
                        questions.stream()
                                .filter(item -> item.id().equals(id))
                                .findFirst()
                                .orElseThrow(
                                        () ->
                                                new ApiException(
                                                        ErrorCode.INVALID_PARAM.getCode(),
                                                        "题目不存在: " + id));
                if (!selected.contains(q)) selected.add(q);
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
                new AiChatRequest(question, List.of(), mode, k, List.of(), options),
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

    public static boolean judge(String answer, String keywords) {
        if (keywords == null || keywords.isEmpty()) return false;
        for (String group : keywords.split("\\|", -1)) {
            boolean hit = false;
            for (String alternative : group.split("/", -1))
                if (!alternative.trim().isEmpty() && answer.contains(alternative.trim()))
                    hit = true;
            if (!hit) return false;
        }
        return true;
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

    private List<EvalQuestionVO> loadQuestions() {
        Map<String, String> keywords = new LinkedHashMap<>();
        for (String[] row : readCsv("eval/keywords.csv")) keywords.put(row[0], row[1]);
        List<EvalQuestionVO> result = new ArrayList<>();
        for (String[] row : readCsv("eval/questions.csv")) {
            String type =
                    switch (row[1]) {
                        case "单文档" -> "single";
                        case "跨文档" -> "cross";
                        case "库外" -> "out";
                        default -> throw new IllegalStateException("题型错误");
                    };
            if (!keywords.containsKey(row[0])) throw new IllegalStateException("缺少判分关键词");
            result.add(new EvalQuestionVO(row[0], type, row[2], keywords.get(row[0]), row[4]));
        }
        if (result.size() != 13) throw new IllegalStateException("题库应包含13题");
        return List.copyOf(result);
    }

    private List<String[]> readCsv(String path) {
        var stream = getClass().getClassLoader().getResourceAsStream(path);
        if (stream == null) throw new IllegalStateException("缺少题库资源: " + path);
        try (var reader =
                new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            reader.readLine();
            return reader.lines()
                    .filter(line -> !line.isBlank())
                    .map(line -> line.split(",", -1))
                    .toList();
        } catch (Exception error) {
            throw new IllegalStateException("题库读取失败", error);
        }
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
