package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.model.dto.FeedbackRequest;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
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

    @PostMapping("/messages/{id}/feedback")
    @Operation(operationId = "submitFeedback", summary = "👍 / 👎")
    public Result<Void> submit(
            @PathVariable String id, @RequestBody(required = false) FeedbackRequest request) {
        throw new ApiException(50101, "尚未实现");
    }

    @GetMapping("/feedback/summary")
    @Operation(operationId = "getFeedbackSummary", summary = "反馈汇总")
    public Result<Object> summary() {
        throw new ApiException(50101, "尚未实现");
    }
}
