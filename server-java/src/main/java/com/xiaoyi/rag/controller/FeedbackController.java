package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.model.dto.FeedbackRequest;
import com.xiaoyi.rag.model.vo.FeedbackSummaryVO;
import com.xiaoyi.rag.service.FeedbackService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** 反馈闭环：2 条对外接口（operationId submitFeedback / getFeedbackSummary）。 */
@RestController
@RequestMapping("/api/v1")
@Tag(name = "评测")
public class FeedbackController {

    private final FeedbackService feedbackService;

    public FeedbackController(FeedbackService feedbackService) {
        this.feedbackService = feedbackService;
    }

    @PostMapping("/messages/{id}/feedback")
    @Operation(operationId = "submitFeedback", summary = "👍 / 👎")
    public Result<Void> submit(
            @PathVariable String id,
            @Valid @RequestBody(required = false) FeedbackRequest request) {
        feedbackService.submit(id, request);
        return Result.ok();
    }

    @GetMapping("/feedback/summary")
    @Operation(operationId = "getFeedbackSummary", summary = "反馈汇总")
    public Result<FeedbackSummaryVO> summary() {
        return Result.ok(feedbackService.summary());
    }
}
