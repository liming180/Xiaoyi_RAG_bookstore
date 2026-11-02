package com.xiaoyi.rag.client.dto;

import java.util.List;

/**
 * 入库任务进度，对应内部契约 {@code IngestTask}。
 *
 * <p>{@code stage} 是 Python 侧原始值，**不能直接透给前端**：契约只允许 parsing/splitting/embedding/summarizing/done
 * 五值， Python 内部可能多出 embed / index / rewrite 之类的阶段名，映射在 Java 侧做（{@code
 * IndexServiceImpl#normalizeStage}）。
 *
 * <p>{@code chunks} 不是内部契约的字段，是本项目的扩展：建库成功后 Python 一次性把片段清单回传， Java 缓存进 chunk 表供 {@code GET
 * /api/v1/chunks} 使用。为空时表示该次轮询没有新片段（Python 还没算完）。
 */
public record AiIngestTask(
        String taskId,
        String status,
        String stage,
        Integer progress,
        Integer docCount,
        Integer chunkCount,
        String error,
        List<AiChunk> chunks) {}
