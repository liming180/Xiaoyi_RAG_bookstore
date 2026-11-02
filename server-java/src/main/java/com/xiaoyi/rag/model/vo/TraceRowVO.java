package com.xiaoyi.rag.model.vo;

/**
 * 检索轨迹中的一行，对应契约 {@code components.schemas.TraceRow}。
 *
 * <p>required 12 项、{@code additionalProperties: false}，一个都不能少。
 *
 * @param rank 排名，从 1 开始
 * @param chunkId 片段号，形如 {@code D02-C001}
 * @param docId 资料 id
 * @param docTitle 资料标题
 * @param headingPath 章节路径
 * @param text 片段正文
 * @param start 原文起始偏移
 * @param end 原文结束偏移（不含）
 * @param score 相关性得分 0..1
 * @param retrieved 是否进入最终 top-k 上下文
 * @param kind 片段类型 chunk/summary/rule
 * @param verified 是否人工审核通过
 */
public record TraceRowVO(
        Integer rank,
        String chunkId,
        String docId,
        String docTitle,
        String headingPath,
        String text,
        Integer start,
        Integer end,
        Double score,
        Boolean retrieved,
        String kind,
        Boolean verified) {}
