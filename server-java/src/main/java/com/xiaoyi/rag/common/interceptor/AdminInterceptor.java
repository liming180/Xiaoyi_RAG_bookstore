package com.xiaoyi.rag.common.interceptor;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.model.entity.User;
import com.xiaoyi.rag.repository.UserRepository;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

/**
 * 管理端闸门：只挂在 {@code /api/v1/admin/**}，要求当前 token 对应的账号是未软删的 ADMIN。
 *
 * <p><b>为什么每次请求都查库，而不是把 role 塞进 JWT：</b>
 *
 * <ul>
 *   <li>JWT 是无状态的，塞进 role 之后「撤销权限」只能等 token 过期（默认 3600s）。管理员被降级或删除后， 旧 token 在 TTL 内仍然能调管理接口 ——
 *       这是实打实的越权窗口。
 *   <li>管理端接口低频（建号/改号/删号），主键点查只取 {@code role} + {@code deleted} 两列，成本可以忽略； 用这点成本换「即时收权」是划算的。
 *   <li>用户端的 29 条接口维持现状（不查库），本拦截器不改变它们的行为。
 * </ul>
 *
 * <p>失败一律回 HTTP 403 + {@code 40101「无权访问该资源」}：契约 §2 把「已认证但无权限」映射到 403 ↔ 401xx， 复用现有码不新增。注意 40101
 * 不会触发前端自动登出（只有 401/40100 会），所以普通用户误入管理端时 只是被提示无权访问，不会把正常会话踢掉。
 */
@Component
public class AdminInterceptor implements HandlerInterceptor {

    private final UserRepository users;
    private final ObjectMapper objectMapper;

    public AdminInterceptor(UserRepository users, ObjectMapper objectMapper) {
        this.users = users;
        this.objectMapper = objectMapper;
    }

    @Override
    public boolean preHandle(
            HttpServletRequest request, HttpServletResponse response, Object handler)
            throws IOException {
        if ("OPTIONS".equalsIgnoreCase(request.getMethod())) {
            return true;
        }
        Object attr = request.getAttribute(AuthInterceptor.ATTR_USER_ID);
        Long userId = attr instanceof Long value ? value : null;
        if (userId == null || userId <= 0) {
            // AuthInterceptor 已经先拦过无 token 的请求；走到这里说明装配顺序被打乱，
            // 按「未认证」失败关闭，绝不放行。
            writeUnauthorized(response);
            return false;
        }
        User user = users.findByIdAndDeletedFalse(userId).orElse(null);
        if (user == null || !"ADMIN".equals(user.getRole())) {
            writeForbidden(response);
            return false;
        }
        return true;
    }

    private void writeUnauthorized(HttpServletResponse response) throws IOException {
        write(
                response,
                HttpStatus.UNAUTHORIZED,
                ErrorCode.UNAUTHENTICATED.getCode(),
                ErrorCode.UNAUTHENTICATED.getDefaultMessage());
    }

    private void writeForbidden(HttpServletResponse response) throws IOException {
        write(response, HttpStatus.FORBIDDEN, ErrorCode.ACCESS_DENIED.getCode(), "无权访问该资源");
    }

    private void write(HttpServletResponse response, HttpStatus status, int code, String message)
            throws IOException {
        response.setStatus(status.value());
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        Result<Void> body = Result.fail(code, message);
        response.getWriter().write(objectMapper.writeValueAsString(body));
    }
}
