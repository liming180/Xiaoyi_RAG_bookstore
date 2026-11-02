package com.xiaoyi.rag;

import com.xiaoyi.rag.config.XiaoyiProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.flyway.FlywayMigrationStrategy;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * 小忆 RAG 问答系统 · Java 业务服务入口。
 *
 * <p>阶段 J1 只负责「能启动、能回统一信封、未实现路由统一 50101」， 不承载任何 RAG 逻辑。
 *
 * <p>{@code @EnableScheduling} 供 J4 的建库任务轮询使用（{@code @Scheduled(fixedDelayString =
 * "${xiaoyi.index.poll-interval-ms:1000}")}）。
 */
@SpringBootApplication
@EnableConfigurationProperties(XiaoyiProperties.class)
@EnableScheduling
public class XiaoyiRagApplication {

    private static final Logger log = LoggerFactory.getLogger(XiaoyiRagApplication.class);

    public static void main(String[] args) {
        SpringApplication.run(XiaoyiRagApplication.class, args);
    }

    /**
     * 手册要求「数据库连不上也要能启动」。
     *
     * <p>Flyway 默认在迁移失败时终止启动，这里包一层：迁移失败打出完整 WARN（不静默吞）， 应用继续起来——J1 阶段全部业务路由返回 50101，不依赖任何表。 DB
     * 恢复后重启即会正常迁移。
     */
    @Bean
    public FlywayMigrationStrategy lenientFlywayMigrationStrategy() {
        return flyway -> {
            try {
                flyway.migrate();
                log.info(
                        "Flyway 迁移完成，当前 schema version = {}",
                        flyway.info().current() == null
                                ? "none"
                                : flyway.info().current().getVersion());
            } catch (Exception ex) {
                log.warn(
                        "Flyway 迁移跳过（数据库不可用或未初始化）：{} - {}",
                        ex.getClass().getSimpleName(),
                        ex.getMessage());
            }
        };
    }
}
