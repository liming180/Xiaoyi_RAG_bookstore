package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.result.Result;
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
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

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

    @GetMapping("/questions")
    @Operation(operationId = "listEvalQuestions", summary = "题库 T01-T13")
    public Result<List<EvalQuestionVO>> questions() {
        return Result.ok(eval.questions());
    }

    @PostMapping("/batch")
    @Operation(operationId = "startEvalBatch", summary = "批量对照评测")
    public Result<?> batch(@RequestBody EvalBatchRequest request) {
        return Result.ok(EvalRunSummaryVO.from(eval.start(request)));
    }

    @GetMapping("/runs")
    @Operation(operationId = "listEvalRuns", summary = "评测批次列表")
    public Result<?> runs() {
        return Result.ok(eval.runs().stream().map(EvalRunSummaryVO::from).toList());
    }

    @GetMapping("/runs/{id}")
    @Operation(operationId = "getEvalRun", summary = "单次评测详情")
    public Result<?> run(@PathVariable String id) {
        return Result.ok(eval.run(id));
    }

    @GetMapping("/candidates")
    @Operation(operationId = "listEvalCandidates", summary = "badcase 候选池")
    public Result<?> candidates() {
        return Result.ok(feedback.candidates());
    }

    @PostMapping("/candidates/{id}/decision")
    @Operation(operationId = "decideEvalCandidate", summary = "候选采纳 / 忽略")
    public Result<Void> decide(
            @PathVariable String id, @RequestBody CandidateDecisionRequest request) {
        feedback.decide(id, request);
        return Result.ok();
    }

    @PostMapping("/experiments")
    @Operation(operationId = "createExperiment", summary = "创建参数实验")
    public Result<?> create(@RequestBody CreateExperimentRequest request) {
        return Result.ok(experiments.create(request));
    }
}
