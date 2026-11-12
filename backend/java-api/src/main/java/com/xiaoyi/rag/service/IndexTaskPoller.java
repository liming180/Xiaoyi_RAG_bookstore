package com.xiaoyi.rag.service;

import com.xiaoyi.rag.service.impl.IndexServiceImpl;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * 建库任务轮询器：每秒推进一次非终态任务。
 *
 * <p>为什么单独成 bean 而不是在 {@link IndexServiceImpl} 上打 {@code @Scheduled}：轮询是基础设施职责， 和业务编排混在一个类里会让
 * {@code IndexServiceImpl} 既是「接口实现」又是「定时任务」， 单测里想手动推进一次还得绕开调度器。分开之后 {@code pollOnce()} 可以直接调。
 *
 * <p>间隔用配置项 {@code xiaoyi.index.poll-interval-ms}（默认 1000）。用 {@code fixedDelay} 而不是 {@code
 * fixedRate}：一次轮询里可能有多个任务、每个都要发 HTTP，固定频率会让请求堆积。
 */
@Component
public class IndexTaskPoller {

    private static final Logger log = LoggerFactory.getLogger(IndexTaskPoller.class);

    private final IndexService indexService;

    public IndexTaskPoller(IndexService indexService) {
        this.indexService = indexService;
    }

    /** 每秒推进一格。 */
    @Scheduled(fixedDelayString = "${xiaoyi.index.poll-interval-ms:1000}")
    public void poll() {
        try {
            indexService.pollOnce();
        } catch (RuntimeException ex) {
            // 定时任务里抛异常会让 Spring 停掉后续调度（取决于异常处理器配置），这里必须自己兜住。
            log.error("建库任务轮询异常：{} - {}", ex.getClass().getSimpleName(), ex.getMessage());
        }
    }
}
