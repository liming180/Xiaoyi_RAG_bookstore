package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.interceptor.AuthInterceptor;
import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.common.support.CurrentUser;
import com.xiaoyi.rag.model.dto.RebuildRequest;
import com.xiaoyi.rag.model.vo.IndexStatusVO;
import com.xiaoyi.rag.model.vo.IndexTaskVO;
import com.xiaoyi.rag.service.IndexService;
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
 * 索引：3 条对外接口。
 *
 * <p>operationId：getIndexStatus / rebuildIndex / getIndexTask。
 *
 * <p>H2 起三条路由都必须带身份：状态、重建、任务轮询全部只对本人资料生效， 别人的 taskId 一律按「不存在」回 40402。
 */
@RestController
@RequestMapping("/api/v1/index")
@Tag(name = "索引")
public class IndexController {

    private final IndexService indexService;

    public IndexController(IndexService indexService) {
        this.indexService = indexService;
    }

    @GetMapping("/status")
    @Operation(operationId = "getIndexStatus", summary = "索引状态")
    public Result<IndexStatusVO> status(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId) {
        return Result.ok(indexService.status(CurrentUser.require(userId)));
    }

    @PostMapping("/rebuild")
    @Operation(operationId = "rebuildIndex", summary = "重建索引，异步返回任务")
    public Result<IndexTaskVO> rebuild(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId,
            @Valid @RequestBody(required = false) RebuildRequest request) {
        Long current = CurrentUser.require(userId);
        if (request == null) {
            // 契约 requestBody 是 required，但缺 body 时给默认参数更友好，不报错。
            return Result.ok(indexService.rebuild(current, null));
        }
        return Result.ok(indexService.rebuild(current, request));
    }

    @GetMapping("/tasks/{id}")
    @Operation(operationId = "getIndexTask", summary = "轮询建库任务")
    public Result<IndexTaskVO> task(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId,
            @PathVariable String id) {
        return Result.ok(indexService.task(CurrentUser.require(userId), id));
    }
}
