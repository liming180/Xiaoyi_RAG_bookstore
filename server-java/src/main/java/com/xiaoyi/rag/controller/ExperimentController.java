package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.common.result.Result;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 参数实验的查询两条（operationId getExperiment / getExperimentReport）。
 *
 * <p>与 {@link EvalController} 的 createExperiment 同属 /api/v1/eval/experiments， 分开只是为了文件别太长。
 */
@RestController
@RequestMapping("/api/v1/eval/experiments")
@Tag(name = "评测")
public class ExperimentController {

    @GetMapping("/{id}")
    @Operation(operationId = "getExperiment", summary = "实验进度")
    public Result<Object> get(@PathVariable String id) {
        throw new ApiException(50101, "尚未实现");
    }

    @GetMapping("/{id}/report")
    @Operation(operationId = "getExperimentReport", summary = "实验报告（experiment + runs）")
    public Result<Object> report(@PathVariable String id) {
        throw new ApiException(50101, "尚未实现");
    }
}
