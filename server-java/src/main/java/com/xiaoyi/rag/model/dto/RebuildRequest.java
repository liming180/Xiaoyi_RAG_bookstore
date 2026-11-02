package com.xiaoyi.rag.model.dto;

import jakarta.validation.constraints.NotNull;

/**
 * 重建索引请求，对应契约 {@code RebuildRequest}。
 *
 * <p>**区间校验故意不放在这里**：Bean Validation 的 {@code @Min/@Max} 触发的是 {@code
 * MethodArgumentNotValidException}，全局异常处理器统一翻成 {@code 40001}；而契约 {@code /api/v1/index/rebuild} 的
 * {@code x-error-codes} 明确要求越界回 {@code 40002}（片段长度）与 {@code
 * 40003}（重叠字数）。这两个码有独立的业务含义，前端按码给不同的输入框报错。
 *
 * <p>所以这里只保留「必填」这一层（缺字段 → 40001，与「值不合法」是两类问题）， 区间与跨字段关系（{@code overlap < chunkSize}）在 {@code
 * IndexServiceImpl} 里判。
 */
public record RebuildRequest(
        @NotNull(message = "片段长度不能为空") Integer chunkSize,
        @NotNull(message = "重叠字数不能为空") Integer overlap) {}
