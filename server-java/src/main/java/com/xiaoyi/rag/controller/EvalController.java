package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.interceptor.AuthInterceptor;
import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.common.support.CurrentUser;
import com.xiaoyi.rag.model.dto.CandidateDecisionRequest;
import com.xiaoyi.rag.model.dto.CreateExperimentRequest;
import com.xiaoyi.rag.model.dto.EvalBatchRequest;
import com.xiaoyi.rag.model.vo.EvalQuestionVO;
import com.xiaoyi.rag.model.vo.EvalRunSummaryVO;
import com.xiaoyi.rag.service.EvalService;
import com.xiaoyi.rag.service.ExperimentService;
import com.xiaoyi.rag.service.FeedbackService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 评测：题库、批量对照、批次详情、候选池、参数实验。
 *
 * <p>每个端点都先经 {@link CurrentUser#require(Long)} 取当前用户：拦截器已经保证认证通过，这里是最后一道 fail-closed 闸门，
 * 也彻底去掉了早期的「拿不到 userId 就当用户 1」兜底。
 */
@RestController
@RequestMapping("/api/v1/eval")
@Tag(name = "评测")
public class EvalController {
    private final EvalService eval;
    private final ExperimentService experiments;
    private final FeedbackService feedback;

    public EvalController(
            EvalService eval, ExperimentService experiments, FeedbackService feedback) {
        this.eval = eval;
        this.experiments = experiments;
        this.feedback = feedback;
    }

    /**
     * 题库 T01-T13。
     *
     * @param userId 拦截器写入的当前用户
     * @return 题库
     */
    @GetMapping("/questions")
    @Operation(operationId = "listEvalQuestions", summary = "题库 T01-T13")
    public Result<List<EvalQuestionVO>> questions(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId) {
        CurrentUser.require(userId);
        return Result.ok(eval.questions());
    }

    /**
     * 批量对照评测。
     *
     * @param userId 拦截器写入的当前用户
     * @param request 模式与 top-k
     * @return 初始批次摘要
     */
    @PostMapping("/batch")
    @Operation(operationId = "startEvalBatch", summary = "批量对照评测")
    public Result<?> batch(
            @RequestBody EvalBatchRequest request,
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId) {
        return Result.ok(EvalRunSummaryVO.from(eval.start(CurrentUser.require(userId), request)));
    }

    /**
     * 评测批次列表。
     *
     * @param userId 拦截器写入的当前用户
     * @return 当前用户的批次摘要列表
     */
    @GetMapping("/runs")
    @Operation(operationId = "listEvalRuns", summary = "评测批次列表")
    public Result<?> runs(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId) {
        return Result.ok(
                eval.runs(CurrentUser.require(userId)).stream()
                        .map(EvalRunSummaryVO::from)
                        .toList());
    }

    /**
     * 单次评测详情。
     *
     * @param id 批次 id
     * @param userId 拦截器写入的当前用户
     * @return 批次详情
     */
    @GetMapping("/runs/{id}")
    @Operation(operationId = "getEvalRun", summary = "单次评测详情")
    public Result<?> run(
            @PathVariable String id,
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId) {
        return Result.ok(eval.run(CurrentUser.require(userId), id));
    }

    /**
     * badcase 候选池。
     *
     * @param userId 拦截器写入的当前用户
     * @return 当前用户自己的候选
     */
    @GetMapping("/candidates")
    @Operation(operationId = "listEvalCandidates", summary = "badcase 候选池")
    public Result<?> candidates(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId) {
        return Result.ok(feedback.candidates(CurrentUser.require(userId)));
    }

    /**
     * 候选采纳 / 忽略。
     *
     * @param id 候选 id
     * @param request 目标状态
     * @param userId 拦截器写入的当前用户
     * @return 空信封
     */
    @PostMapping("/candidates/{id}/decision")
    @Operation(operationId = "decideEvalCandidate", summary = "候选采纳 / 忽略")
    public Result<Void> decide(
            @PathVariable String id,
            @RequestBody CandidateDecisionRequest request,
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId) {
        feedback.decide(CurrentUser.require(userId), id, request);
        return Result.ok();
    }

    /**
     * 创建参数实验。
     *
     * @param request 参数轴
     * @param userId 拦截器写入的当前用户
     * @return 初始实验视图
     */
    @PostMapping("/experiments")
    @Operation(operationId = "createExperiment", summary = "创建参数实验")
    public Result<?> create(
            @RequestBody CreateExperimentRequest request,
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId) {
        return Result.ok(experiments.create(CurrentUser.require(userId), request));
    }
}
