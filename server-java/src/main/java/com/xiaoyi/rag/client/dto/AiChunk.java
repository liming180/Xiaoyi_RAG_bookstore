package com.xiaoyi.rag.client.dto;

/**
 * 一个片段，来自 Python 建库结果的回传。
 *
 * <p>字段名用 camelCase，Python 侧下发的是 snake_case（{@code chunk_id} / {@code doc_title} / {@code
 * heading_path}）， 由 {@code AiServiceClient} 的实现负责改名 —— 转换集中在一处，Service 层不再关心命名风格。
 */
public record AiChunk(
        String chunkId,
        String docId,
        String docTitle,
        String headingPath,
        String text,
        Integer start,
        Integer end,
        String kind,
        Boolean verified) {}
