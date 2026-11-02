package com.xiaoyi.rag.common.interceptor;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.result.Result;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

/**
 * J1 的极简鉴权闸门：受保护路径必须带 {@code Authorization: Bearer <token>}。
 *
 * <p>阶段 1 是演示模式（固定用户），这里只校验头存在且非空，不验签； J2 接入真正的 JWT 解析后，把 userId 换成从 token 里取。
 *
 * <p>放行白名单在 {@link com.xiaoyi.rag.config.WebMvcConfig} 里配置： {@code /api/v1/auth/login}、{@code
 * /api/v1/health}。
 */
@Component
public class AuthInterceptor implements HandlerInterceptor {

    /** 请求属性名：当前用户 id。J2 之后由 token 解析填充。 */
    public static final String ATTR_USER_ID = "xiaoyi.userId";

    private static final String BEARER_PREFIX = "Bearer ";

    private final ObjectMapper objectMapper;

    public AuthInterceptor(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    @Override
    public boolean preHandle(
            HttpServletRequest request, HttpServletResponse response, Object handler)
            throws IOException {
        if (HttpMethod.OPTIONS.matches(request.getMethod())) {
            return true;
        }
        String header = request.getHeader(HttpHeaders.AUTHORIZATION);
        if (header == null
                || !header.startsWith(BEARER_PREFIX)
                || header.substring(BEARER_PREFIX.length()).isBlank()) {
            writeUnauthorized(response);
            return false;
        }
        request.setAttribute(ATTR_USER_ID, 1L);
        return true;
    }

    private void writeUnauthorized(HttpServletResponse response) throws IOException {
        response.setStatus(HttpStatus.UNAUTHORIZED.value());
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        Result<Void> body =
                Result.fail(
                        ErrorCode.UNAUTHENTICATED.getCode(),
                        ErrorCode.UNAUTHENTICATED.getDefaultMessage());
        response.getWriter().write(objectMapper.writeValueAsString(body));
    }
}
