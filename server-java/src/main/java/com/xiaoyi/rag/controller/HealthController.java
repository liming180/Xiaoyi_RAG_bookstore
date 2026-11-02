package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.model.vo.HealthVO;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 健康检查：J1 唯一一条真接口（不占用 28 条清单里的 operationId）。
 *
 * <p>返回 {@code Result.ok({status:"UP"})}，用于前端启动探活与测试用例断言。
 */
@RestController
@RequestMapping("/api/v1")
@Tag(name = "鉴权")
public class HealthController {

    @GetMapping("/health")
    @Operation(summary = "健康检查")
    public Result<HealthVO> health() {
        return Result.ok(HealthVO.up());
    }
}
