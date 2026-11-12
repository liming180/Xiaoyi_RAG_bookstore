package com.xiaoyi.rag.config;

import com.xiaoyi.rag.common.interceptor.AdminInterceptor;
import com.xiaoyi.rag.common.interceptor.AuthInterceptor;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * MVC 装配：注册鉴权与管理端两级拦截器。
 *
 * <p>白名单：登录与健康检查（前端启动时无需 token 即可探活）。
 *
 * <p>顺序有意义：{@link AuthInterceptor} 先验签并把 userId 放进 request 属性，{@link AdminInterceptor}
 * 才能读到它去查库判角色。管理端拦截器只挂 {@code /api/v1/admin/**}，用户端 29 条接口的行为完全不变。
 */
@Configuration
public class WebMvcConfig implements WebMvcConfigurer {

    private final AuthInterceptor authInterceptor;
    private final AdminInterceptor adminInterceptor;

    public WebMvcConfig(AuthInterceptor authInterceptor, AdminInterceptor adminInterceptor) {
        this.authInterceptor = authInterceptor;
        this.adminInterceptor = adminInterceptor;
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(authInterceptor)
                .addPathPatterns("/api/v1/**")
                .excludePathPatterns("/api/v1/auth/login", "/api/v1/health");

        registry.addInterceptor(adminInterceptor).addPathPatterns("/api/v1/admin/**");
    }
}
