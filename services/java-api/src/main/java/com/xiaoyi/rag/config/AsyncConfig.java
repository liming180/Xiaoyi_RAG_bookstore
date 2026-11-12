package com.xiaoyi.rag.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

/**
 * 问答落库专用线程池。
 *
 * <p>手册 §7 明令「不许在 SSE 线程里做数据库写入（会阻塞流），必须异步」。这里单独给一个小池子， 而不是复用 Spring 默认的 {@code
 * applicationTaskExecutor}：落库是短任务但要保证顺序（用户消息先于助手消息）， 池子大了反而容易在并发对话时抢连接。
 *
 * <p>队列容量给 200：极端情况下（客户端疯狂发问）宁可拒绝也不无限堆积内存。
 */
@Configuration
public class AsyncConfig {

    /** 落库线程池的 bean 名，注入时按名字取。 */
    public static final String CHAT_PERSIST_EXECUTOR = "chatPersistExecutor";

    /**
     * 问答落库线程池。
     *
     * @return 2 个核心线程、队列 200 的执行器
     */
    @Bean(name = CHAT_PERSIST_EXECUTOR)
    public ThreadPoolTaskExecutor chatPersistExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(2);
        executor.setMaxPoolSize(4);
        executor.setQueueCapacity(200);
        executor.setThreadNamePrefix("chat-persist-");
        executor.setWaitForTasksToCompleteOnShutdown(true);
        executor.setAwaitTerminationSeconds(10);
        executor.initialize();
        return executor;
    }
}
