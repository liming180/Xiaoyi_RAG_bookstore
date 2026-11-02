package com.xiaoyi.rag.config;

import java.util.List;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * 跨域配置：只放行前端 dev / preview 端口。
 *
 * <p>白名单来自 {@code xiaoyi.cors.allowed-origins}，由 {@link XiaoyiProperties} 绑定。
 */
@Configuration
public class CorsConfig implements WebMvcConfigurer {

    private final XiaoyiProperties properties;

    public CorsConfig(XiaoyiProperties properties) {
        this.properties = properties;
    }

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        List<String> allowedOrigins = properties.getCors().getAllowedOrigins();
        String[] origins = allowedOrigins.toArray(new String[0]);
        registry.addMapping("/api/**")
                .allowedOrigins(origins)
                .allowedMethods("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS")
                .allowedHeaders("*")
                .exposedHeaders("Content-Type")
                .allowCredentials(true)
                .maxAge(3600);
        registry.addMapping("/actuator/**")
                .allowedOrigins(origins)
                .allowedMethods("GET", "OPTIONS")
                .maxAge(3600);
    }
}
