package com.xiaoyi.rag.client.dto;

/**
 * Python 侧索引状态，对应内部契约 {@code IndexManifest}。
 *
 * <p>只有 {@code ready} / {@code needs_rebuild} 两值 —— {@code unavailable} 是 Java 侧的合成值（Python 不可达时），
 * Python 不会回。
 */
public record AiIndexManifest(
        String status,
        String embeddingModel,
        Integer chunkSize,
        Integer overlap,
        Integer docCount,
        Integer chunkCount,
        Long builtAt,
        String sha256,
        String reason) {}
