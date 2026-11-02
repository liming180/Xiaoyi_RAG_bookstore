package com.xiaoyi.rag.model.vo;

/**
 * 索引状态，对应契约 {@code components.schemas.IndexStatus}。
 *
 * <p>契约 required：{@code [status, docCount, chunkCount, chunkSize, overlap, embeddingModel,
 * lastBuiltAt]}，{@code additionalProperties: false}。{@code reason} 与 {@code manifest} 可空。
 *
 * <p>{@code status=unavailable} 是**成功响应**（HTTP 200），不是 503 —— 契约 {@code /api/v1/index/status} 的
 * {@code x-error-codes} 只有 40100/50000。前端靠这个值区分「Python 挂了」与「请求失败」， 若这里抛
 * 503，前端只能看到一个笼统的失败，无法展示「知识库暂时不可用」的降级文案。
 *
 * @param status ready / needs_rebuild / unavailable
 * @param docCount 已入库资料数
 * @param chunkCount 片段总数
 * @param chunkSize 当前生效的片段长度
 * @param overlap 当前生效的重叠字数
 * @param embeddingModel embedding 模型名
 * @param lastBuiltAt 上次成功建库时间（Unix 秒），从未建库为 null
 * @param reason 需要重建或不可用的原因，正常为 null 且不输出
 * @param manifest 上次建库的清单快照，从未建库为 null 且不输出
 */
public record IndexStatusVO(
        String status,
        Integer docCount,
        Integer chunkCount,
        Integer chunkSize,
        Integer overlap,
        String embeddingModel,
        Long lastBuiltAt,
        String reason,
        IndexManifestVO manifest) {}
