package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.model.dto.CandidateDecisionRequest;
import com.xiaoyi.rag.model.dto.CreateExperimentRequest;
import com.xiaoyi.rag.model.dto.EvalBatchRequest;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 评测：7 条对外接口。
 *
 * <p>operationId：listEvalQuestions / startEvalBatch / listEvalRuns / getEvalRun /
 * listEvalCandidates / decideEvalCandidate / createExperiment， 另有 getExperiment /
 * getExperimentReport 归在 {@link ExperimentController}。
 */
@RestController
@RequestMapping("/api/v1/eval")
@Tag(name = "评测")
public class EvalController {

    @GetMapping("/questions")
    @Operation(operationId = "listEvalQuestions", summary = "题库 T01-T10")
    public Result<Object> questions() {
        throw new ApiException(50101, "尚未实现");
    }

    @PostMapping("/batch")
    @Operation(operationId = "startEvalBatch", summary = "批量对照评测")
    public Result<Object> batch(@RequestBody(required = false) EvalBatchRequest request) {
        throw new ApiException(50101, "尚未实现");
    }

    @GetMapping("/runs")
    @Operation(operationId = "listEvalRuns", summary = "评测批次列表")
    public Result<Object> runs() {
        throw new ApiException(50101, "尚未实现");
    }

    @GetMapping("/runs/{id}")
    @Operation(operationId = "getEvalRun", summary = "单次评测详情（含逐题 cases）")
    public Result<Object> run(@PathVariable String id) {
        throw new ApiException(50101, "尚未实现");
    }

    @GetMapping("/candidates")
    @Operation(operationId = "listEvalCandidates", summary = "badcase 候选池")
    public Result<Object> candidates() {
        throw new ApiException(50101, "尚未实现");
    }

    @PostMapping("/candidates/{id}/decision")
    @Operation(operationId = "decideEvalCandidate", summary = "采纳 / 忽略候选")
    public Result<Void> decide(
            @PathVariable String id,
            @RequestBody(required = false) CandidateDecisionRequest request) {
        throw new ApiException(50101, "尚未实现");
    }

    @PostMapping("/experiments")
    @Operation(operationId = "createExperiment", summary = "创建参数实验")
    public Result<Object> createExperiment(
            @RequestBody(required = false) CreateExperimentRequest request) {
        throw new ApiException(50101, "尚未实现");
    }
}
