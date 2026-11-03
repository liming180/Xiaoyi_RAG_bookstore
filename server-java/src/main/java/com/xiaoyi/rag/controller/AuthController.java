package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.common.interceptor.AuthInterceptor;
import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.model.dto.LoginRequest;
import com.xiaoyi.rag.model.entity.User;
import com.xiaoyi.rag.model.vo.LoginResultVO;
import com.xiaoyi.rag.model.vo.UserInfoVO;
import com.xiaoyi.rag.repository.UserRepository;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import java.util.UUID;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** 演示模式鉴权：固定用户体系，保留后续 JWT 接入所需的响应契约。 */
@RestController
@RequestMapping("/api/v1/auth")
@Tag(name = "鉴权")
public class AuthController {

    private static final long DEMO_USER_ID = 1L;
    private static final long TOKEN_EXPIRES_IN_SECONDS = 86_400L;
    private static final String TOKEN_PREFIX = "demo-";

    private final UserRepository userRepository;
    private final AuthInterceptor authInterceptor;

    public AuthController(UserRepository userRepository, AuthInterceptor authInterceptor) {
        this.userRepository = userRepository;
        this.authInterceptor = authInterceptor;
    }

    @PostMapping("/login")
    @Operation(operationId = "login", summary = "登录换取 token")
    public Result<LoginResultVO> login(@Valid @RequestBody LoginRequest request) {
        User user = findOrCreateDemoUser(request.username().trim());
        UserInfoVO userInfo = toUserInfo(user);
        String token = TOKEN_PREFIX + UUID.randomUUID();
        authInterceptor.registerDemoToken(token, user.getId());
        return Result.ok(new LoginResultVO(token, TOKEN_EXPIRES_IN_SECONDS, userInfo));
    }

    @GetMapping("/profile")
    @Operation(operationId = "getProfile", summary = "当前登录用户")
    public Result<UserInfoVO> profile(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId) {
        long id = userId == null ? DEMO_USER_ID : userId;
        User user = userRepository.findById(id).orElseThrow(() -> new ApiException(40100, "登录已过期"));
        return Result.ok(toUserInfo(user));
    }

    private User findOrCreateDemoUser(String username) {
        return userRepository
                .findByUsername(username)
                .orElseGet(
                        () -> {
                            User user = new User();
                            user.setUsername(username);
                            user.setPasswordHash("demo");
                            user.setRole("USER");
                            return userRepository.save(user);
                        });
    }

    private UserInfoVO toUserInfo(User user) {
        String displayName =
                "demo".equalsIgnoreCase(user.getUsername()) ? "演示用户" : user.getUsername();
        return new UserInfoVO(user.getId(), user.getUsername(), displayName);
    }
}
