package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.interceptor.AuthInterceptor;
import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.model.dto.LoginRequest;
import com.xiaoyi.rag.model.vo.LoginResultVO;
import com.xiaoyi.rag.model.vo.UserInfoVO;
import com.xiaoyi.rag.service.AuthService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth")
@Tag(name = "鉴权")
public class AuthController {
    private final AuthService auth;

    public AuthController(AuthService auth) {
        this.auth = auth;
    }

    @PostMapping("/login")
    @Operation(operationId = "login", summary = "登录换取 token")
    public Result<LoginResultVO> login(@Valid @RequestBody LoginRequest request) {
        return Result.ok(auth.login(request));
    }

    @GetMapping("/profile")
    @Operation(operationId = "getProfile", summary = "当前登录用户")
    public Result<UserInfoVO> profile(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId) {
        return Result.ok(auth.profile(userId));
    }
}
