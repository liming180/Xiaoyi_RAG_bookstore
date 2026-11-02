package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.model.dto.RebuildRequest;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 索引：3 条对外接口。
 *
 * <p>operationId：getIndexStatus / rebuildIndex / getIndexTask。
 */
@RestController
@RequestMapping("/api/v1/index")
@Tag(name = "索引")
public class IndexController {

    @GetMapping("/status")
    @Operation(operationId = "getIndexStatus", summary = "索引状态")
    public Result<Object> status() {
        throw new ApiException(50101, "尚未实现");
    }

    @PostMapping("/rebuild")
    @Operation(operationId = "rebuildIndex", summary = "重建索引，异步返回任务")
    public Result<Object> rebuild(@Valid @RequestBody(required = false) RebuildRequest request) {
        throw new ApiException(50101, "尚未实现");
    }

    @GetMapping("/tasks/{id}")
    @Operation(operationId = "getIndexTask", summary = "轮询建库任务")
    public Result<Object> task(@PathVariable String id) {
        throw new ApiException(50101, "尚未实现");
    }
}
