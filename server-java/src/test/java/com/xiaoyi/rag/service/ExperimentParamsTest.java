package com.xiaoyi.rag.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.config.XiaoyiProperties;
import com.xiaoyi.rag.model.dto.CreateExperimentRequest;
import com.xiaoyi.rag.model.dto.RebuildRequest;
import com.xiaoyi.rag.model.entity.EvalCandidate;
import com.xiaoyi.rag.model.entity.Experiment;
import com.xiaoyi.rag.model.entity.ExperimentRun;
import com.xiaoyi.rag.model.vo.EvalCaseResultVO;
import com.xiaoyi.rag.model.vo.EvalQuestionVO;
import com.xiaoyi.rag.model.vo.IndexStatusVO;
import com.xiaoyi.rag.model.vo.IndexTaskVO;
import com.xiaoyi.rag.repository.EvalCandidateRepository;
import com.xiaoyi.rag.repository.ExperimentRepository;
import com.xiaoyi.rag.repository.ExperimentRunRepository;
import com.xiaoyi.rag.service.impl.ExperimentServiceImpl;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionStatus;

/**
 * N1：参数实验的 `chunkSize` / `overlap` 轴必须真的重建向量库。
 *
 * <p>修这个缺陷之前，四根轴里三根是装饰：`ExperimentServiceImpl` 只把 `k` 传给 `evaluations.evaluate(...)`，其余三个键随
 * `params_json` 落库后无人读取。对比表里两行 参数不同、数字却完全一样 —— 仪器不准，后面所有「混合检索有没有变好」的结论都不可信。
 *
 * <p>这里只验编排：本组参数与「当前生效参数」不同 → 调 `rebuildForExperiment`； 整场跑完 → 再用默认 180/30
 * 重建一次恢复；`metrics.effective` 如实标出 summary 未生效。
 *
 * <p>所有 stub 都用 {@code doAnswer(...).when(...)} 而不是 {@code when(mock.call())}： 后者在装桩时就会真的调一次
 * mock，把「重建次数」这类计数器污染掉。
 */
class ExperimentParamsTest {

    private static final Long OWNER = 3L;

    private final ExperimentRepository experiments = mock(ExperimentRepository.class);
    private final ExperimentRunRepository runs = mock(ExperimentRunRepository.class);
    private final EvalService eval = mock(EvalService.class);
    private final IndexService indexes = mock(IndexService.class);

    private final EvalCandidateRepository candidates = mock(EvalCandidateRepository.class);
    private final PlatformTransactionManager manager = mock(PlatformTransactionManager.class);

    /** 每次 rebuildForExperiment 收到的参数，按调用顺序。 */
    private final List<RebuildRequest> rebuilds = new CopyOnWriteArrayList<>();

    /** 让本组（第一组）的重建失败：按任务 id 前缀区分。 */
    private final List<String> failingTasks = new CopyOnWriteArrayList<>();

    private final ExperimentServiceImpl service;

    ExperimentParamsTest() {
        when(manager.getTransaction(any())).thenReturn(mock(TransactionStatus.class));
        XiaoyiProperties properties = new XiaoyiProperties();
        properties.getIndex().setDefaultChunkSize(180);
        properties.getIndex().setDefaultOverlap(30);
        service =
                new ExperimentServiceImpl(
                        experiments,
                        runs,
                        eval,
                        indexes,
                        properties,
                        new ObjectMapper(),
                        manager,
                        candidates);

        Experiment experiment = new Experiment();
        experiment.setName("params");
        experiment.setStatus("RUNNING");
        experiment.setProgress(0);
        experiment.setTotalGroups(1);
        experiment.setFinishedGroups(0);
        experiment.setCreatedAt(1L);
        try {
            var id = Experiment.class.getDeclaredField("id");
            id.setAccessible(true);
            id.set(experiment, 1L);
        } catch (ReflectiveOperationException failure) {
            throw new IllegalStateException(failure);
        }
        when(experiments.saveAndFlush(any())).thenReturn(experiment);
        when(experiments.findByIdAndUserId(1L, OWNER)).thenReturn(Optional.of(experiment));
        when(experiments.save(any())).thenAnswer(call -> call.getArgument(0));
        when(runs.save(any())).thenAnswer(call -> call.getArgument(0));
        when(eval.questions())
                .thenReturn(List.of(new EvalQuestionVO("T01", "fact", "问题", "关键词", "asset")));
        when(eval.evaluate(anyLong(), any(), anyInt(), any()))
                .thenAnswer(
                        call ->
                                List.of(
                                        new EvalCaseResultVO(
                                                "T01",
                                                "fact",
                                                "问题",
                                                "直答",
                                                true,
                                                "查资料答案",
                                                true,
                                                List.of("D01-C001"),
                                                12L)));
    }

    @BeforeEach
    void stubIndexService() {
        rebuilds.clear();
        failingTasks.clear();
        doAnswer(
                        call -> {
                            RebuildRequest request = call.getArgument(1);
                            rebuilds.add(request);
                            return task("task-" + rebuilds.size(), "PENDING");
                        })
                .when(indexes)
                .rebuildForExperiment(anyLong(), any());
        doAnswer(
                        call -> {
                            String id = call.getArgument(1);
                            boolean failed =
                                    failingTasks.stream().anyMatch(prefix -> id.startsWith(prefix));
                            return task(id, failed ? "FAILED" : "SUCCEEDED");
                        })
                .when(indexes)
                .task(anyLong(), anyString());
    }

    @Test
    void chunkSizeAxisRebuildsIndexAndRestoresDefaults() throws Exception {
        // 当前生效参数是默认 180/30，本组要 300/30 —— 必须触发一次重建。
        when(indexes.status(OWNER)).thenReturn(status(180, 30));

        service.create(OWNER, request(List.of(300), List.of(30)));
        awaitIdle();

        // 两次：本组参数一次，收尾恢复默认一次。
        assertThat(rebuilds).hasSize(2);
        assertThat(rebuilds.get(0).chunkSize()).isEqualTo(300);
        assertThat(rebuilds.get(0).overlap()).isEqualTo(30);
        assertThat(rebuilds.get(1).chunkSize()).isEqualTo(180);
        assertThat(rebuilds.get(1).overlap()).isEqualTo(30);
    }

    @Test
    void matchingParamsTouchNothing() throws Exception {
        // 当前生效参数已经是本组参数：本组不必重建，收尾也不必恢复（一次都没动过向量库）。
        // 这条很重要 —— 默认矩阵（180/30）是最常用的，不该每次实验都白跑两次建库。
        when(indexes.status(OWNER)).thenReturn(status(180, 30));

        service.create(OWNER, request(List.of(180), List.of(30)));
        awaitIdle();

        assertThat(rebuilds).isEmpty();
    }

    @Test
    void metricsRecordEffectiveFlagsWithSummaryStillFalse() throws Exception {
        when(indexes.status(OWNER)).thenReturn(status(180, 30));

        service.create(OWNER, request(List.of(300), List.of(30)));
        awaitIdle();

        ArgumentCaptor<ExperimentRun> saved = ArgumentCaptor.forClass(ExperimentRun.class);
        verify(runs, atLeastOnce()).save(saved.capture());
        String metrics = saved.getValue().getMetricsJson();
        assertThat(metrics).contains("\"effective\"");
        // summary 轴在 N3 落地前恒为 false，不许假装生效。
        assertThat(metrics).contains("\"summary\":false");
        assertThat(metrics).contains("\"chunkSize\":true");
        assertThat(metrics).contains("\"overlap\":true");
        assertThat(metrics).contains("\"rerank\":true");
        assertThat(metrics).contains("\"k\":true");
    }

    @Test
    void rebuildFailureMarksOnlyThatGroupAndKeepsGoing() throws Exception {
        when(indexes.status(OWNER)).thenReturn(status(180, 30));
        // 第一组（本组参数）的重建失败；收尾那次（task-2）成功。
        failingTasks.add("task-1");

        service.create(OWNER, request(List.of(300), List.of(30)));
        awaitIdle();

        ArgumentCaptor<ExperimentRun> saved = ArgumentCaptor.forClass(ExperimentRun.class);
        verify(runs, atLeastOnce()).save(saved.capture());
        String metrics = saved.getValue().getMetricsJson();
        assertThat(metrics).contains("本组建库失败");
        // 本组失败不评测，但收尾恢复照跑：两次重建都发出去了。
        assertThat(rebuilds).hasSize(2);
        verify(eval, never()).evaluate(anyLong(), any(), anyInt(), any());
    }

    @Test
    void moreThanEightGroupsIsRejected() {
        assertThatThrownBy(
                        () ->
                                service.create(
                                        OWNER,
                                        request(List.of(180, 300, 500), List.of(30, 50, 100))))
                .isInstanceOfSatisfying(
                        ApiException.class, error -> assertThat(error.getCode()).isEqualTo(40001));
        verify(experiments, never()).saveAndFlush(any());
        assertThat(service.isRunning()).isFalse();
    }

    /* ------------------------------------------- N4：候选题进实验的计分边界 */

    /**
     * 候选题补了关键词 → 计入分母。
     *
     * <p>观测点是 {@code metrics.scored / unscored} 与 hitRate 的分母：T01 + C8 共 2 题、都有关键词， 那么 scored 必须是
     * 2，hitRate 是「判定通过数 / 2」而不是 / 题数以外的任何东西。
     */
    @Test
    void acceptedCandidateWithKeywordsCountsTowardHitRate() throws Exception {
        stubTwoQuestionsWithCandidate("4本/4册");
        when(indexes.status(OWNER)).thenReturn(status(180, 30));

        service.create(OWNER, candidateRequest(List.of("T01", "C8")));
        awaitIdle();

        String metrics = lastMetrics();
        assertThat(metrics).contains("\"scored\":2");
        assertThat(metrics).contains("\"unscored\":0");
    }

    /**
     * 候选题没补关键词 → 照样跑，但不进分母。
     *
     * <p>这条是整个 N4 的判定核心：没有关键词就判不出对错（{@code judge()} 恒 false）。 如果把这种题算进分母，用户每采纳一道没补关键词的候选，hitRate
     * 就会莫名其妙掉一截 —— 而他自己什么都没做错。
     */
    @Test
    void acceptedCandidateWithoutKeywordsIsUnscoredAndExcludedFromDenominator() throws Exception {
        stubTwoQuestionsWithCandidate(null);
        when(indexes.status(OWNER)).thenReturn(status(180, 30));

        service.create(OWNER, candidateRequest(List.of("T01", "C8")));
        awaitIdle();

        String metrics = lastMetrics();
        assertThat(metrics).contains("\"scored\":1");
        assertThat(metrics).contains("\"unscored\":1");
        // 1 题通过 / 1 道可计分题 = 1.0；不是 1/2。分母错了这条会变成 0.5。
        assertThat(metrics).contains("\"hitRate\":1.0");
    }

    /** 只有候选题、且全都没关键词：分母为 0，hitRate 记 0 而不是 NaN / Infinity。 */
    @Test
    void allUnscoredQuestionsReportZeroHitRate() throws Exception {
        stubTwoQuestionsWithCandidate(null);
        when(indexes.status(OWNER)).thenReturn(status(180, 30));

        service.create(OWNER, candidateRequest(List.of("C8")));
        awaitIdle();

        String metrics = lastMetrics();
        assertThat(metrics).contains("\"scored\":0");
        assertThat(metrics).contains("\"unscored\":1");
        assertThat(metrics).contains("\"hitRate\":0.0");
    }

    /** pending 候选（还没采纳）不能进实验：与「题号写错」同一条 40001，不给存在性信号。 */
    @Test
    void pendingCandidateCannotJoinExperiment() {
        // findOwnedByIdAndStatus 只认 accepted；candidates mock 默认回 Optional.empty()。
        assertThatThrownBy(() -> service.create(OWNER, candidateRequest(List.of("C8"))))
                .isInstanceOfSatisfying(
                        ApiException.class,
                        error -> {
                            assertThat(error.getCode()).isEqualTo(40001);
                            assertThat(error.getMessage()).contains("题目不存在: C8");
                        });
        verify(experiments, never()).saveAndFlush(any());
        assertThat(service.isRunning()).isFalse();
    }

    /** 题号不是 C<数字> 的形式，与「题号不存在」同样处理，不抛 NumberFormatException。 */
    @Test
    void malformedCandidateIdIsInvalidParam() {
        assertThatThrownBy(() -> service.create(OWNER, candidateRequest(List.of("Cabc"))))
                .isInstanceOfSatisfying(
                        ApiException.class, error -> assertThat(error.getCode()).isEqualTo(40001));
        verify(experiments, never()).saveAndFlush(any());
    }

    /* ------------------------------------------------------------ 工具 */

    /** 让题库回一道 T01，候选池回一道 C8（关键词按入参，null = 没补）。 */
    private void stubTwoQuestionsWithCandidate(String keywords) {
        EvalCandidate candidate = new EvalCandidate();
        candidate.setQuestion("这本书能借几天？");
        candidate.setKeywords(keywords);
        when(candidates.findOwnedByIdAndStatus(8L, OWNER, "accepted"))
                .thenReturn(Optional.of(candidate));
        // evaluate 必须按传进来的题数返回：题数对不上会被 execute 判成「结果数量不完整」。
        when(eval.evaluate(anyLong(), any(), anyInt(), any()))
                .thenAnswer(
                        call -> {
                            List<EvalQuestionVO> asked = call.getArgument(1);
                            return asked.stream()
                                    .map(
                                            q ->
                                                    new EvalCaseResultVO(
                                                            q.id(),
                                                            q.type(),
                                                            q.question(),
                                                            "直答",
                                                            true,
                                                            "查资料答案",
                                                            true,
                                                            List.of("D01-C001"),
                                                            10L))
                                    .toList();
                        });
    }

    private String lastMetrics() {
        ArgumentCaptor<ExperimentRun> saved = ArgumentCaptor.forClass(ExperimentRun.class);
        verify(runs, atLeastOnce()).save(saved.capture());
        return saved.getValue().getMetricsJson();
    }

    private CreateExperimentRequest candidateRequest(List<String> questionIds) {
        return new CreateExperimentRequest(
                "candidate",
                questionIds,
                new CreateExperimentRequest.ExperimentAxis(
                        List.of(180), List.of(30), List.of(3), List.of(true), List.of(false)));
    }

    private void awaitIdle() throws InterruptedException {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (service.isRunning() && System.nanoTime() < deadline) Thread.onSpinWait();
        assertThat(service.isRunning()).isFalse();
    }

    private CreateExperimentRequest request(List<Integer> chunk, List<Integer> overlap) {
        return new CreateExperimentRequest(
                "params",
                List.of("T01"),
                new CreateExperimentRequest.ExperimentAxis(
                        chunk, overlap, List.of(3), List.of(true), List.of(false)));
    }

    private static IndexStatusVO status(int chunkSize, int overlap) {
        return new IndexStatusVO(
                "ready", 1, 8, chunkSize, overlap, "mock-embedding", 1L, null, null);
    }

    private static IndexTaskVO task(String id, String status) {
        boolean ok = "SUCCEEDED".equals(status);
        return new IndexTaskVO(
                id, status, "done", ok ? 100 : 50, 180, 30, 1, 8, 1L, ok ? 2L : null, null);
    }
}
