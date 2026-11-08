package com.xiaoyi.rag.service.impl;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.config.XiaoyiProperties;
import com.xiaoyi.rag.model.dto.CreateExperimentRequest;
import com.xiaoyi.rag.model.dto.RebuildRequest;
import com.xiaoyi.rag.model.entity.Experiment;
import com.xiaoyi.rag.model.entity.ExperimentRun;
import com.xiaoyi.rag.model.vo.EvalCaseResultVO;
import com.xiaoyi.rag.model.vo.ExperimentReportVO;
import com.xiaoyi.rag.model.vo.ExperimentVO;
import com.xiaoyi.rag.model.vo.IndexTaskVO;
import com.xiaoyi.rag.repository.ExperimentRepository;
import com.xiaoyi.rag.repository.ExperimentRunRepository;
import com.xiaoyi.rag.service.EvalService;
import com.xiaoyi.rag.service.ExperimentService;
import com.xiaoyi.rag.service.IndexService;
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

    /** 参数矩阵最多几组。每组都要重建一次索引（真实 embedding + Milvus 约 6 秒），再多就没人等了。 */
    private static final int MAX_GROUPS = 8;

    /** 单组重建索引的等待上限（毫秒）。真实 embedding 8 片段约 6 秒，留足 120 秒余量。 */
    private static final long REBUILD_TIMEOUT_MS = 120_000L;

    /** 轮询建库任务的间隔（毫秒）。与 Java 侧 IndexTaskPoller 的 1s 节拍一致。 */
    private static final long REBUILD_POLL_MS = 500L;

    /**
     * `summary` 轴当前是否真生效。
     *
     * <p>N3（全局摘要卡）落地前恒为 {@code false}：建库管线的 summarizing 阶段只更新进度、 不生成摘要卡，所以 summary=true/false
     * 两组跑出来完全一样。把这里改成 true 需要先 让 {@code server-ai/app/services/ingest.py} 真的产出 D00 摘要卡。
     */
    private static final boolean SUMMARY_AXIS_EFFECTIVE = false;

    private final ExperimentRepository experiments;
    private final ExperimentRunRepository runs;
    private final EvalService evaluations;
    private final IndexService indexes;
    private final XiaoyiProperties properties;
    private final ObjectMapper mapper;
    private final TransactionTemplate transactions;
    private final AtomicBoolean running = new AtomicBoolean();

    public ExperimentServiceImpl(
            ExperimentRepository experiments,
            ExperimentRunRepository runs,
            EvalService evaluations,
            IndexService indexes,
            XiaoyiProperties properties,
            ObjectMapper mapper,
            PlatformTransactionManager manager) {
        this.experiments = experiments;
        this.runs = runs;
        this.evaluations = evaluations;
        this.indexes = indexes;
        this.properties = properties;
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
        if (groups.size() > MAX_GROUPS)
            throw new ApiException(
                    ErrorCode.INVALID_PARAM.getCode(), "参数矩阵最多 " + MAX_GROUPS + " 组（每组都要重建索引）");
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

    /**
     * 后台串行执行每一组：**先按本组参数重建索引，再评测**。
     *
     * <p>为什么必须重建：`chunkSize` / `overlap` 是建库参数，片段一旦切好就固化在向量库里。 只把它们写进 `params_json`
     * 落库、却拿同一份向量库去跑所有组，报告里的两行参数不同、 数字却完全一样 —— 这就是「仪器不准」。真实做法是每组开始前按本组参数重建一次，
     * 跑完再恢复到用户原本的推荐参数（180/30）。
     *
     * <p>失败策略分三层：
     *
     * <ul>
     *   <li>某一组重建失败 → 该组标 FAILED 并记 error，**继续下一组**，不整场中断；
     *   <li>评测本身抛异常 → 整场 FAILED（题集为空、AI 不可用属于环境问题，继续跑没有意义）；
     *   <li>收尾恢复默认参数失败 → 整场 FAILED，error 写明「向量库未能恢复到默认参数」。
     * </ul>
     */
    private void execute(Long userId, Long id, List<Map<String, Object>> groups) {
        boolean indexTouched = false;
        try {
            var questions = evaluations.questions();
            if (questions.isEmpty()) throw new IllegalStateException("评测题集为空");
            for (int index = 0; index < groups.size(); index++) {
                if (Thread.currentThread().isInterrupted())
                    throw new IllegalStateException("实验已中断");
                Map<String, Object> params = groups.get(index);
                long start = System.nanoTime();

                // 1) 让本组的 chunkSize / overlap 真正作用到向量库上。
                AlignResult aligned = alignIndex(userId, params);
                // 只要动过向量库（哪怕重建失败），收尾就必须尝试恢复默认：
                // 重建失败也可能已经删掉了旧片段，留着不管等于把用户的知识库搞成半残。
                indexTouched = indexTouched || aligned.rebuilt();
                String rebuildError = aligned.error();

                Map<String, Object> metrics = new LinkedHashMap<>();
                long elapsed;
                if (rebuildError != null) {
                    // 本组作废：指标留 0，错误如实写进 metrics.error，继续下一组。
                    metrics.put("hitRate", 0.0d);
                    metrics.put("avgElapsedMs", 0L);
                    metrics.put("avgSources", 0);
                    metrics.put("failed", questions.size());
                    metrics.put("error", "本组建库失败，未评测：" + rebuildError);
                    elapsed = Math.max(0, (System.nanoTime() - start) / 1_000_000);
                } else {
                    List<EvalCaseResultVO> cases =
                            evaluations.evaluate(
                                    userId, questions, (Integer) params.get("k"), params);
                    if (cases.size() != questions.size())
                        throw new IllegalStateException("评测结果数量不完整");
                    elapsed = Math.max(0, (System.nanoTime() - start) / 1_000_000);
                    long passed = cases.stream().filter(EvalCaseResultVO::ragPassed).count();
                    long failed =
                            cases.stream()
                                    .filter(c -> c.ragAnswer() == null || c.ragAnswer().isBlank())
                                    .count();
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
                                    .mapToInt(
                                            c -> c.ragSources() == null ? 0 : c.ragSources().size())
                                    .average()
                                    .orElse(0));
                    metrics.put("failed", failed);
                }
                // 本组到底哪几根轴真的生效了 —— 这一栏是本任务的验收核心，不许假装。
                metrics.put("effective", effectiveFlags());

                final int groupIndex = index;
                final long groupElapsed = elapsed;
                transactions.executeWithoutResult(
                        status -> {
                            ExperimentRun run = new ExperimentRun();
                            run.setExperimentId(id);
                            run.setGroupIndex(groupIndex);
                            run.setParamsJson(json(params));
                            run.setMetricsJson(json(metrics));
                            run.setElapsedMs(groupElapsed);
                            runs.save(run);
                            Experiment experiment = require(userId, id);
                            experiment.setFinishedGroups(groupIndex + 1);
                            experiment.setProgress((groupIndex + 1) * 100 / groups.size());
                            experiments.save(experiment);
                        });
            }

            // 2) 收尾：把向量库恢复到用户原本的推荐参数，否则实验一跑完，日常问答就建在实验参数上。
            String restoreError = indexTouched ? restoreDefaults(userId) : null;
            if (restoreError != null) {
                finish(userId, id, "FAILED", "向量库未能恢复到默认参数：" + restoreError);
            } else {
                finish(userId, id, "SUCCEEDED", null);
            }
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

    /**
     * 把向量库对齐到本组的 chunkSize / overlap。
     *
     * @param userId 归属用户
     * @param params 本组参数
     * @return 对齐结果：{@code error} 为 null 表示成功；{@code rebuilt} 表示本次是否真的动过向量库
     */
    private AlignResult alignIndex(Long userId, Map<String, Object> params) {
        int chunkSize = ((Number) params.get("chunkSize")).intValue();
        int overlap = ((Number) params.get("overlap")).intValue();
        try {
            var current = indexes.status(userId);
            if (current != null
                    && Integer.valueOf(chunkSize).equals(current.chunkSize())
                    && Integer.valueOf(overlap).equals(current.overlap())) {
                return new AlignResult(null, false);
            }
            var task = indexes.rebuildForExperiment(userId, new RebuildRequest(chunkSize, overlap));
            var done = awaitTask(userId, task.id());
            if ("SUCCEEDED".equals(done.status())) return new AlignResult(null, true);
            String reason = done.error() == null ? "建库任务 " + done.status() : done.error();
            return new AlignResult(reason, true);
        } catch (RuntimeException ex) {
            String reason =
                    ex.getMessage() == null ? ex.getClass().getSimpleName() : ex.getMessage();
            // 抛异常也可能是「rebuild 已经受理、轮询期间失败」，保守按动过处理。
            return new AlignResult(reason, true);
        }
    }

    /**
     * 一次参数对齐的结果。
     *
     * @param error 失败原因；成功为 null
     * @param rebuilt 本次是否真的动过向量库（用于决定收尾要不要恢复默认参数）
     */
    private record AlignResult(String error, boolean rebuilt) {}

    /**
     * 实验结束后恢复推荐参数；返回 {@code null} 表示恢复成功。
     *
     * @param userId 归属用户
     * @return 失败原因；成功为 null
     */
    private String restoreDefaults(Long userId) {
        try {
            var task =
                    indexes.rebuildForExperiment(
                            userId,
                            new RebuildRequest(
                                    properties.getIndex().getDefaultChunkSize(),
                                    properties.getIndex().getDefaultOverlap()));
            var done = awaitTask(userId, task.id());
            if ("SUCCEEDED".equals(done.status())) return null;
            return done.error() == null ? "建库任务 " + done.status() : done.error();
        } catch (RuntimeException ex) {
            return ex.getMessage() == null ? ex.getClass().getSimpleName() : ex.getMessage();
        }
    }

    /**
     * 轮询建库任务到终态。
     *
     * <p>超时按 FAILED 处理：真实 embedding + Milvus 单次重建约 6 秒，120 秒还没跑完说明 Python 侧卡住了，继续等只会让整个实验卡死。
     *
     * @param userId 归属用户
     * @param taskId 任务 id
     * @return 终态任务视图
     */
    private IndexTaskVO awaitTask(Long userId, String taskId) {
        long deadline = System.nanoTime() + REBUILD_TIMEOUT_MS * 1_000_000L;
        IndexTaskVO last = null;
        while (System.nanoTime() < deadline) {
            if (Thread.currentThread().isInterrupted()) throw new IllegalStateException("实验已中断");
            last = indexes.task(userId, taskId);
            String status = last == null ? null : last.status();
            if ("SUCCEEDED".equals(status) || "FAILED".equals(status)) return last;
            try {
                Thread.sleep(REBUILD_POLL_MS);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException("实验已中断", interrupted);
            }
        }
        throw new IllegalStateException(
                "建库任务 " + taskId + " 超过 " + (REBUILD_TIMEOUT_MS / 1000) + " 秒未结束");
    }

    /**
     * 本组「哪几根轴真的生效」。
     *
     * <p>{@code summary} 轴在 N3（全局摘要卡）落地前恒为 {@code false} —— 参数能填、能落库， 但建库管线根本不生成摘要卡，把它标成 true
     * 就是自欺。前端按这一栏灰显未生效的轴。
     *
     * @return 轴名 → 是否生效
     */
    private Map<String, Object> effectiveFlags() {
        Map<String, Object> flags = new LinkedHashMap<>();
        flags.put("k", true);
        flags.put("rerank", true);
        flags.put("chunkSize", true);
        flags.put("overlap", true);
        flags.put("summary", SUMMARY_AXIS_EFFECTIVE);
        return flags;
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
