package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.model.vo.AdminAuditPageVO;
import com.xiaoyi.rag.service.AuditService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 管理端 · 审计日志查询。
 *
 * <p>整组路径由 {@code AdminInterceptor} 保护（非 ADMIN 一律 403/40101），与用户管理同一套闸门。
 *
 * <p><b>只读</b>：没有任何 POST/PUT/DELETE。审计日志是账本，能改就不是审计了。
 */
@RestController
@RequestMapping("/api/v1/admin/audit-logs")
@Tag(name = "管理端-审计日志")
public class AdminAuditController {

    private final AuditService auditService;

    public AdminAuditController(AuditService auditService) {
        this.auditService = auditService;
    }

    @GetMapping
    @Operation(operationId = "adminListAuditLogs", summary = "审计日志分页查询")
    public Result<AdminAuditPageVO> list(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) String action,
            @RequestParam(required = false) Long operatorId,
            @RequestParam(required = false) String keyword) {
        return Result.ok(auditService.list(page, size, action, operatorId, keyword));
    }

    @GetMapping("/actions")
    @Operation(operationId = "adminListAuditActions", summary = "出现过的动作名（筛选下拉用）")
    public Result<List<String>> actions() {
        return Result.ok(auditService.actions());
    }
}
