package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.interceptor.AuthInterceptor;
import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.common.support.CurrentUser;
import com.xiaoyi.rag.model.dto.AdminUserCreateRequest;
import com.xiaoyi.rag.model.dto.AdminUserPasswordRequest;
import com.xiaoyi.rag.model.dto.AdminUserUpdateRequest;
import com.xiaoyi.rag.model.vo.AdminUserItemVO;
import com.xiaoyi.rag.model.vo.AdminUserPageVO;
import com.xiaoyi.rag.service.UserService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 管理端 · 用户管理。
 *
 * <p>整组路径由 {@code AdminInterceptor} 保护（非 ADMIN 一律 403/40101），控制器内部不再重复判角色 —— 但操作者 id 仍需 {@link
 * CurrentUser#require} 取出来写审计：拦截器只保证「是管理员」， 不负责告诉业务层「是谁」。
 *
 * <p>本控制器不提供「把某人改成 ADMIN」的入口，也不接受 {@code role} 字段 —— 全系统只有一个管理员。
 */
@RestController
@RequestMapping("/api/v1/admin/users")
@Tag(name = "管理端-用户管理")
public class AdminUserController {

    private final UserService userService;

    public AdminUserController(UserService userService) {
        this.userService = userService;
    }

    @GetMapping
    @Operation(operationId = "adminListUsers", summary = "用户分页列表")
    public Result<AdminUserPageVO> list(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) String keyword,
            @RequestParam(defaultValue = "false") boolean includeDeleted) {
        return Result.ok(userService.list(page, size, keyword, includeDeleted));
    }

    @PostMapping
    @Operation(operationId = "adminCreateUser", summary = "新建用户")
    public Result<AdminUserItemVO> create(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false)
                    Long operatorId,
            @Valid @RequestBody AdminUserCreateRequest request) {
        return Result.ok(userService.create(CurrentUser.require(operatorId), request));
    }

    @PutMapping("/{id}")
    @Operation(operationId = "adminUpdateUser", summary = "编辑用户显示名")
    public Result<AdminUserItemVO> update(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false)
                    Long operatorId,
            @PathVariable Long id,
            @Valid @RequestBody AdminUserUpdateRequest request) {
        return Result.ok(userService.update(CurrentUser.require(operatorId), id, request));
    }

    @PutMapping("/{id}/password")
    @Operation(operationId = "adminResetUserPassword", summary = "重置用户密码")
    public Result<AdminUserItemVO> updatePassword(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false)
                    Long operatorId,
            @PathVariable Long id,
            @Valid @RequestBody AdminUserPasswordRequest request) {
        return Result.ok(userService.updatePassword(CurrentUser.require(operatorId), id, request));
    }

    @DeleteMapping("/{id}")
    @Operation(operationId = "adminDeleteUser", summary = "删除用户（软删）")
    public Result<Void> delete(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false)
                    Long operatorId,
            @PathVariable Long id) {
        userService.delete(CurrentUser.require(operatorId), id);
        return Result.ok();
    }
}
