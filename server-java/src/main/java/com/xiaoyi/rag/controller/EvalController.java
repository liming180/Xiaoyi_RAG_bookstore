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
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
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
     * 导出已采纳候选为题库 CSV。
     *
     * <p><b>为什么直接写 {@code HttpServletResponse} 而不是返回 {@code Result}：</b>这一条回的是 {@code
     * text/csv}，不是统一信封。走 {@code ResponseEntity<String>} 时 Spring 会按请求的 {@code Accept} 做内容协商，而前端
     * axios 默认发的是「json 优先、text 次之、通配兜底」那串 Accept，顺序上 JSON 在前，很容易被转成字符串 JSON（整段 CSV 被包在引号里，Excel
     * 打开是一坨）。 直接往输出流写并显式定 Content-Type，任何 Accept 下都是原样的 CSV。
     *
     * <p>BOM 与这里无关：BOM 是给 Excel 认 UTF-8 的，写在正文第一个字符。
     *
     * @param userId 拦截器写入的当前用户
     * @param response 原始响应，用于写 CSV 与下载头
     * @throws IOException 写流失败
     */
    @GetMapping("/candidates/export")
    @Operation(operationId = "exportEvalCandidates", summary = "导出已采纳候选为题库 CSV")
    public void exportCandidates(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId,
            HttpServletResponse response)
            throws IOException {
        String csv = feedback.exportCandidates(CurrentUser.require(userId));
        response.setStatus(HttpServletResponse.SC_OK);
        // charset 用 UTF-8：正文已经带 BOM，再由容器按 UTF-8 编码写出，Excel 才不会乱码。
        response.setContentType("text/csv;charset=UTF-8");
        response.setHeader(
                HttpHeaders.CONTENT_DISPOSITION,
                ContentDisposition.attachment()
                        .filename("eval-candidates.csv", StandardCharsets.UTF_8)
                        .build()
                        .toString());
        response.getWriter().write(csv);
        response.flushBuffer();
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
