package com.xiaoyi.rag.model.vo;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * 最近一次成功建库的清单快照，对应契约 {@code components.schemas.IndexManifest}。
 *
 * <p>契约 {@code additionalProperties: false} 且**没有 required**：字段全是可选的，但一旦出现就必须类型正确。 所以这里统一用 {@code
 * NON_NULL}——不存在的字段直接不输出，而不是输出 {@code null}（{@code chunkSize} 等是 {@code type: integer}，不是 {@code
 * oneOf [integer, null]}，给 null 会校验失败）。
 *
 * @param embeddingModel embedding 模型名
 * @param chunkSize 建库时用的片段长度
 * @param overlap 建库时用的重叠字数
 * @param docCount 入库资料数
 * @param chunkCount 片段总数
 * @param builtAt 建库完成时间（Unix 秒）
 * @param sha256 语料集合摘要
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record IndexManifestVO(
        String embeddingModel,
        Integer chunkSize,
        Integer overlap,
        Integer docCount,
        Integer chunkCount,
        Long builtAt,
        String sha256) {}
