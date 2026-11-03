package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.service.ExperimentService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/eval/experiments")
@Tag(name = "评测")
public class ExperimentController {
    private final ExperimentService service;

    public ExperimentController(ExperimentService service) {
        this.service = service;
    }

    @GetMapping("/{id}")
    @Operation(operationId = "getExperiment", summary = "实验进度")
    public Result<?> get(@PathVariable String id) {
        return Result.ok(service.get(id));
    }

    @GetMapping("/{id}/report")
    @Operation(operationId = "getExperimentReport", summary = "实验报告")
    public Result<?> report(@PathVariable String id) {
        return Result.ok(service.report(id));
    }
}
