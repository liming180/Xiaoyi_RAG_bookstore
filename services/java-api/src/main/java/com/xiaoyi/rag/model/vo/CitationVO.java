package com.xiaoyi.rag.model.vo;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * 引用视图，对应契约 {@code components.schemas.Citation}。
 *
 * <p>{@code additionalProperties: false} + required 11 项，字段名一个都不能错。
 *
 * <p>{@code ref} 是双形状（整数序号 1..k 或片段号 {@code "D02-C001"}），故用 {@code Object} 承载。 {@code stage} 在契约里不是
 * required，J2 阶段恒为 null，靠 {@code @JsonInclude(NON_NULL)} 省略。
 *
 * @param ref 引用编号，整数或片段号
 * @param chunkId 片段号，形如 {@code D02-C001}
 * @param docId 资料 id
 * @param docTitle 资料标题
 * @param headingPath 章节路径
 * @param text 片段正文
 * @param start 原文起始偏移
 * @param end 原文结束偏移（不含）
 * @param score 相关性得分 0..1
 * @param stage 得分阶段（dense/sparse/rrf/rerank），可空
 * @param kind 片段类型（chunk/summary/rule）
 * @param verified 是否人工审核通过
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record CitationVO(
        Object ref,
        String chunkId,
        String docId,
        String docTitle,
        String headingPath,
        String text,
        Integer start,
        Integer end,
        Double score,
        String stage,
        String kind,
        Boolean verified) {}
