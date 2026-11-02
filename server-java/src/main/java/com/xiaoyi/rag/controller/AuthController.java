package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.model.dto.LoginRequest;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 鉴权：2 条对外接口（operationId login / getProfile）。
 *
 * <p>J1 阶段两条都还是占位，J2 接入演示账号后 login 才会签发真 token。
 */
@RestController
@RequestMapping("/api/v1/auth")
@Tag(name = "鉴权")
public class AuthController {

    @PostMapping("/login")
    @Operation(operationId = "login", summary = "登录换取 token")
    public Result<Map<String, Object>> login(
            @Valid @RequestBody(required = false) LoginRequest request) {
        throw new ApiException(50101, "尚未实现");
    }

    @GetMapping("/profile")
    @Operation(operationId = "getProfile", summary = "当前登录用户")
    public Result<Map<String, Object>> profile() {
        throw new ApiException(50101, "尚未实现");
    }
}
