package com.xiaoyi.rag.config;

import org.springframework.context.annotation.Configuration;

/**
 * 对外部 AI 服务的 HTTP 客户端配置占位。
 *
 * <p>J1 阶段使用 {@code MockAiClient}，不建立真实连接；J6 三端联调时在此装配 带超时与重试的客户端（chat 60s / ingest 提交 10s / 状态查询
 * 5s）， 并统一注入 {@code X-Internal-Token}。
 */
@Configuration
public class WebClientConfig {

    // J6 填充：
    // @Bean WebClient aiWebClient(...) -> baseUrl(xiaoyi.ai.base-url)
    //     .defaultHeader("X-Internal-Token", xiaoyi.ai.internal-token)
    //     .clientConnector(timeout(...))
}
