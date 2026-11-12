package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.interceptor.AuthInterceptor;
import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.common.support.CurrentUser;
import com.xiaoyi.rag.model.dto.FeedbackRequest;
import com.xiaoyi.rag.model.vo.FeedbackSummaryVO;
import com.xiaoyi.rag.service.FeedbackService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 反馈闭环：2 条对外接口（operationId submitFeedback / getFeedbackSummary）。
 *
 * <p>两个端点都以 {@link CurrentUser#require(Long)} 开头：反馈行没有归属列， 用户身份必须由调用方显式带进来，才能在 Service 层做会话归属校验。
 */
@RestController
@RequestMapping("/api/v1")
@Tag(name = "评测")
public class FeedbackController {

    private final FeedbackService feedbackService;

    public FeedbackController(FeedbackService feedbackService) {
        this.feedbackService = feedbackService;
    }

    /**
     * 提交 👍 / 👎。
     *
     * @param id 消息 id
     * @param request 评分、标签、备注
     * @param userId 拦截器写入的当前用户
     * @return 空信封
     */
    @PostMapping("/messages/{id}/feedback")
    @Operation(operationId = "submitFeedback", summary = "👍 / 👎")
    public Result<Void> submit(
            @PathVariable String id,
            @Valid @RequestBody(required = false) FeedbackRequest request,
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId) {
        feedbackService.submit(CurrentUser.require(userId), id, request);
        return Result.ok();
    }

    /**
     * 反馈汇总。
     *
     * @param userId 拦截器写入的当前用户
     * @return 当前用户自己的总量、好评、差评与待处理候选数
     */
    @GetMapping("/feedback/summary")
    @Operation(operationId = "getFeedbackSummary", summary = "反馈汇总")
    public Result<FeedbackSummaryVO> summary(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId) {
        return Result.ok(feedbackService.summary(CurrentUser.require(userId)));
    }
}
