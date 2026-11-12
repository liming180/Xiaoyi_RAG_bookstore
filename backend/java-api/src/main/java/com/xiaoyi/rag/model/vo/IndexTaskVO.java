package com.xiaoyi.rag.model.vo;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * 建库任务视图，对应契约 {@code components.schemas.IndexTask}。
 *
 * <p>契约 required：{@code [id, status, stage, progress, chunkSize, overlap, docCount, chunkCount,
 * startedAt, finishedAt]}，{@code additionalProperties: false}。
 *
 * <p>{@code finishedAt} 是 required 且允许 null，所以**不能**加 {@code NON_NULL}——未结束时必须输出 {@code
 * "finishedAt": null}，否则契约校验会报「缺少必填字段」。{@code error} 相反是可选的，未失败时不输出。
 *
 * @param id 任务 id（Java 侧主键，不是 Python 的 task_id）
 * @param status PENDING / RUNNING / SUCCEEDED / FAILED
 * @param stage parsing / splitting / embedding / summarizing / done
 * @param progress 0..100，终态恒 100（失败停在失败时的值）
 * @param chunkSize 本次建库的片段长度
 * @param overlap 本次建库的重叠字数
 * @param docCount 已入库资料数
 * @param chunkCount 片段总数
 * @param startedAt 创建时间（Unix 秒）
 * @param finishedAt 结束时间（Unix 秒），未结束为 null
 * @param error 失败原因，正常为 null 且不输出
 */
public record IndexTaskVO(
        String id,
        String status,
        String stage,
        Integer progress,
        Integer chunkSize,
        Integer overlap,
        Integer docCount,
        Integer chunkCount,
        Long startedAt,
        Long finishedAt,
        @JsonInclude(JsonInclude.Include.NON_NULL) String error) {}
