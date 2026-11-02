package com.xiaoyi.rag.config;

import java.util.Optional;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.domain.AuditorAware;
import org.springframework.data.jpa.repository.config.EnableJpaAuditing;

/**
 * JPA 审计配置：createdAt / updatedAt 由 Spring Data 自动填充。
 *
 * <p>J1 阶段还没有登录态，auditor 固定返回空；J2 接入鉴权后从 SecurityContext 取。
 */
@Configuration
@EnableJpaAuditing(auditorAwareRef = "auditorProvider")
public class JpaConfig {

    @Bean
    public AuditorAware<String> auditorProvider() {
        return () -> Optional.empty();
    }
}
