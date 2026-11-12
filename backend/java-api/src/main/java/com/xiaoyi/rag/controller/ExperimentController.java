package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.interceptor.AuthInterceptor;
import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.common.support.CurrentUser;
import com.xiaoyi.rag.service.ExperimentService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 实验查询：进度与报告。
 *
 * <p>两个端点都以 {@link CurrentUser#require(Long)} 开头，别人的实验 id 一律按 40405 处理。
 */
@RestController
@RequestMapping("/api/v1/eval/experiments")
@Tag(name = "评测")
public class ExperimentController {
    private final ExperimentService service;

    public ExperimentController(ExperimentService service) {
        this.service = service;
    }

    /**
     * 实验进度。
     *
     * @param id 实验 id
     * @param userId 拦截器写入的当前用户
     * @return 实验视图
     */
    @GetMapping("/{id}")
    @Operation(operationId = "getExperiment", summary = "实验进度")
    public Result<?> get(
            @PathVariable String id,
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId) {
        return Result.ok(service.get(CurrentUser.require(userId), id));
    }

    /**
     * 实验报告。
     *
     * @param id 实验 id
     * @param userId 拦截器写入的当前用户
     * @return 实验视图与逐组指标
     */
    @GetMapping("/{id}/report")
    @Operation(operationId = "getExperimentReport", summary = "实验报告")
    public Result<?> report(
            @PathVariable String id,
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId) {
        return Result.ok(service.report(CurrentUser.require(userId), id));
    }
}
