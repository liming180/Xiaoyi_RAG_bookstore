package com.xiaoyi.rag.service.impl;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.model.dto.CreateExperimentRequest;
import com.xiaoyi.rag.model.entity.Experiment;
import com.xiaoyi.rag.model.entity.ExperimentRun;
import com.xiaoyi.rag.model.vo.EvalCaseResultVO;
import com.xiaoyi.rag.model.vo.ExperimentReportVO;
import com.xiaoyi.rag.model.vo.ExperimentVO;
import com.xiaoyi.rag.repository.ExperimentRepository;
import com.xiaoyi.rag.repository.ExperimentRunRepository;
import com.xiaoyi.rag.service.EvalService;
import com.xiaoyi.rag.service.ExperimentService;
import jakarta.annotation.PostConstruct;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** 实验状态、参数和每组指标全部持久化，后台串行调用真实评测链路。 */
@Service
public class ExperimentServiceImpl implements ExperimentService {
    private final ExperimentRepository experiments;
    private final ExperimentRunRepository runs;
    private final EvalService evaluations;
    private final ObjectMapper mapper;
    private final TransactionTemplate transactions;
    private final AtomicBoolean running = new AtomicBoolean();

    public ExperimentServiceImpl(
            ExperimentRepository experiments,
            ExperimentRunRepository runs,
            EvalService evaluations,
            ObjectMapper mapper,
            PlatformTransactionManager manager) {
        this.experiments = experiments;
        this.runs = runs;
        this.evaluations = evaluations;
        this.mapper = mapper;
        this.transactions = new TransactionTemplate(manager);
    }

    /**
     * 启动时崩溃恢复：跨全部用户扫描非终态实验。
     *
     * <p>重启时没有请求上下文，残留的 PENDING/RUNNING 行无论属于谁都已经没有执行线程，必须统一置 FAILED， 否则进度条永远停在半路。
     */
    @PostConstruct
    public void recoverInterrupted() {
        transactions.executeWithoutResult(
                status -> {
                    for (Experiment experiment :
                            experiments.findByStatusIn(List.of("PENDING", "RUNNING"))) {
                        experiment.setStatus("FAILED");
                        experiment.setError("服务重启，实验已中断");
                        experiment.setFinishedAt(now());
                        experiments.save(experiment);
                    }
                });
    }

    @Override
    public synchronized ExperimentVO create(Long userId, CreateExperimentRequest request) {
        if (running.get())
            throw new ApiException(
                    ErrorCode.EXPERIMENT_ALREADY_RUNNING.getCode(),
                    ErrorCode.EXPERIMENT_ALREADY_RUNNING.getDefaultMessage());
        if (request == null || request.axes() == null)
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "实验参数非法");
        if (request.name() != null && request.name().length() > 255)
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "实验名称过长");
        List<Map<String, Object>> groups = groups(request.axes());
        if (groups.isEmpty())
            throw new ApiException(
                    ErrorCode.EMPTY_PARAM_MATRIX.getCode(),
                    ErrorCode.EMPTY_PARAM_MATRIX.getDefaultMessage());
        running.set(true);
        try {
            Experiment experiment =
                    transactions.execute(
                            status -> {
                                Experiment row = new Experiment();
                                row.setUserId(userId);
                                row.setName(
                                        request.name() == null || request.name().isBlank()
                                                ? "参数实验"
                                                : request.name());
                                row.setStatus("RUNNING");
                                row.setProgress(0);
                                row.setTotalGroups(groups.size());
                                row.setFinishedGroups(0);
                                row.setCreatedAt(now());
                                row.setAxesJson(json(request.axes()));
                                return experiments.saveAndFlush(row);
                            });
            ExperimentVO initial = toVO(experiment);
            Long id = experiment.getId();
            Long owner = userId;
            Thread.startVirtualThread(() -> execute(owner, id, groups));
            return initial;
        } catch (RuntimeException | Error error) {
            running.set(false);
            throw error;
        }
    }

    private void execute(Long userId, Long id, List<Map<String, Object>> groups) {
        try {
            var questions = evaluations.questions();
            if (questions.isEmpty()) throw new IllegalStateException("评测题集为空");
            for (int index = 0; index < groups.size(); index++) {
                if (Thread.currentThread().isInterrupted())
                    throw new IllegalStateException("实验已中断");
                Map<String, Object> params = groups.get(index);
                long start = System.nanoTime();
                List<EvalCaseResultVO> cases =
                        evaluations.evaluate(userId, questions, (Integer) params.get("k"), params);
                if (cases.size() != questions.size()) throw new IllegalStateException("评测结果数量不完整");
                long elapsed = Math.max(0, (System.nanoTime() - start) / 1_000_000);
                long passed = cases.stream().filter(EvalCaseResultVO::ragPassed).count();
                long failed =
                        cases.stream()
                                .filter(c -> c.ragAnswer() == null || c.ragAnswer().isBlank())
                                .count();
                Map<String, Object> metrics = new LinkedHashMap<>();
                metrics.put("hitRate", (double) passed / cases.size());
                metrics.put(
                        "avgElapsedMs",
                        Math.round(
                                cases.stream()
                                        .mapToLong(EvalCaseResultVO::elapsedMs)
                                        .average()
                                        .orElse(0)));
                metrics.put(
                        "avgSources",
                        cases.stream()
                                .mapToInt(c -> c.ragSources() == null ? 0 : c.ragSources().size())
                                .average()
                                .orElse(0));
                metrics.put("failed", failed);
                final int groupIndex = index;
                transactions.executeWithoutResult(
                        status -> {
                            ExperimentRun run = new ExperimentRun();
                            run.setExperimentId(id);
                            run.setGroupIndex(groupIndex);
                            run.setParamsJson(json(params));
                            run.setMetricsJson(json(metrics));
                            run.setElapsedMs(elapsed);
                            runs.save(run);
                            Experiment experiment = require(userId, id);
                            experiment.setFinishedGroups(groupIndex + 1);
                            experiment.setProgress((groupIndex + 1) * 100 / groups.size());
                            experiments.save(experiment);
                        });
            }
            finish(userId, id, "SUCCEEDED", null);
        } catch (Throwable error) {
            finish(
                    userId,
                    id,
                    "FAILED",
                    error.getMessage() == null
                            ? error.getClass().getSimpleName()
                            : error.getMessage());
        } finally {
            running.set(false);
        }
    }

    private void finish(Long userId, Long id, String state, String error) {
        transactions.executeWithoutResult(
                status -> {
                    Experiment experiment = require(userId, id);
                    experiment.setStatus(state);
                    experiment.setError(error);
                    experiment.setFinishedAt(now());
                    if ("SUCCEEDED".equals(state)) experiment.setProgress(100);
                    experiments.save(experiment);
                });
    }

    private List<Map<String, Object>> groups(CreateExperimentRequest.ExperimentAxis axes) {
        if (axes.chunkSize() == null
                || axes.overlap() == null
                || axes.k() == null
                || axes.rerank() == null
                || axes.summary() == null)
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "实验参数轴缺失");
        for (Integer value : axes.chunkSize())
            if (value == null || value < 50 || value > 1000)
                throw new ApiException(
                        ErrorCode.INVALID_CHUNK_SIZE.getCode(), "chunkSize 需在 50-1000 之间");
        for (Integer value : axes.overlap())
            if (value == null || value < 0)
                throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "overlap 必须非负");
        for (Integer value : axes.k())
            if (value == null || value < 1 || value > 10)
                throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "k 需在 1-10 之间");
        if (axes.rerank().stream().anyMatch(v -> v == null)
                || axes.summary().stream().anyMatch(v -> v == null))
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "布尔轴包含空值");
        List<Map<String, Object>> result = new ArrayList<>();
        for (Integer chunk : axes.chunkSize())
            for (Integer overlap : axes.overlap()) {
                if (overlap >= chunk) continue;
                for (Integer k : axes.k())
                    for (Boolean rerank : axes.rerank())
                        for (Boolean summary : axes.summary()) {
                            if (result.size() >= 4096)
                                throw new ApiException(
                                        ErrorCode.INVALID_PARAM.getCode(), "参数矩阵最多 4096 组");
                            Map<String, Object> params = new LinkedHashMap<>();
                            params.put("chunkSize", chunk);
                            params.put("overlap", overlap);
                            params.put("k", k);
                            params.put("rerank", rerank);
                            params.put("summary", summary);
                            result.add(params);
                        }
            }
        return result;
    }

    @Override
    public ExperimentVO get(Long userId, String id) {
        return toVO(require(userId, parseId(id)));
    }

    @Override
    public ExperimentReportVO report(Long userId, String id) {
        Experiment experiment = require(userId, parseId(id));
        List<ExperimentReportVO.Run> report =
                runs.findByExperimentIdOrderByGroupIndexAsc(experiment.getId()).stream()
                        .map(
                                row ->
                                        new ExperimentReportVO.Run(
                                                String.valueOf(row.getId()),
                                                readMap(row.getParamsJson()),
                                                readMap(row.getMetricsJson()),
                                                row.getElapsedMs()))
                        .toList();
        return new ExperimentReportVO(toVO(experiment), report);
    }

    @Override
    public boolean isRunning() {
        return running.get();
    }

    @Override
    public void assertChatAvailable() {
        if (running.get())
            throw new ApiException(
                    ErrorCode.EXPERIMENT_BUSY.getCode(),
                    ErrorCode.EXPERIMENT_BUSY.getDefaultMessage());
    }

    /**
     * 按 id + 归属用户取实验。
     *
     * <p>别人的实验与不存在的 id 走同一个 40405 分支，避免用状态码枚举出别人的 id。
     */
    private Experiment require(Long userId, Long id) {
        return experiments
                .findByIdAndUserId(id, userId)
                .orElseThrow(
                        () ->
                                new ApiException(
                                        ErrorCode.EXPERIMENT_NOT_FOUND.getCode(),
                                        ErrorCode.EXPERIMENT_NOT_FOUND.getDefaultMessage()));
    }

    private Long parseId(String id) {
        try {
            long value = Long.parseLong(id);
            if (value > 0) return value;
        } catch (NumberFormatException ignored) {
            // 契约 ID 是字符串；格式不符也按资源不存在处理。
        }
        throw new ApiException(
                ErrorCode.EXPERIMENT_NOT_FOUND.getCode(),
                ErrorCode.EXPERIMENT_NOT_FOUND.getDefaultMessage());
    }

    private ExperimentVO toVO(Experiment row) {
        return new ExperimentVO(
                String.valueOf(row.getId()),
                row.getName(),
                row.getStatus(),
                row.getProgress(),
                row.getTotalGroups(),
                row.getFinishedGroups(),
                row.getCreatedAt(),
                row.getFinishedAt(),
                row.getError());
    }

    private String json(Object value) {
        try {
            return mapper.writeValueAsString(value);
        } catch (Exception error) {
            throw new IllegalStateException("实验 JSON 序列化失败", error);
        }
    }

    private Map<String, Object> readMap(String value) {
        try {
            return mapper.readValue(value, new TypeReference<Map<String, Object>>() {});
        } catch (Exception error) {
            throw new IllegalStateException("实验 JSON 解析失败", error);
        }
    }

    private long now() {
        return Instant.now().getEpochSecond();
    }
}
