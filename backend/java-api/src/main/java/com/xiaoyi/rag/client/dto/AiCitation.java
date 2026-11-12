package com.xiaoyi.rag.client.dto;

/**
 * 内部契约的单条引用（snake_case 语义，对应 docs/api/openapi-internal.yaml#/components/schemas/InternalCitation）。
 *
 * <p>与对外 Citation 的差异：{@code excerpt} ↔ {@code text}、{@code chunk_id} ↔ {@code chunkId}、 {@code
 * score_stage} ↔ {@code stage}、{@code doc_title} ↔ {@code docTitle}、{@code heading_path} ↔ {@code
 * headingPath}。转换发生在 service 层，不在这里做。
 *
 * <p>{@code ref} 用 {@code Object} 而不是 {@code String}：内部契约里它也是双形状（整数序号或片段号）， 若声明成 String，Jackson 会把
 * {@code ref: 1} 悄悄转成 {@code "1"}，再吐给前端时形状就变了 —— 对外 Citation 的 {@code CitationRef} 是 oneOf(integer,
 * string)，两者都得原样保留。
 *
 * @param ref 引用编号，整数序号或片段号字符串
 * @param chunkId 片段号，形如 {@code D02-C001}
 * @param docId 资料 id
 * @param docTitle 资料标题
 * @param headingPath 章节路径
 * @param excerpt 片段正文（对外叫 {@code text}）
 * @param start 原文起始偏移
 * @param end 原文结束偏移（不含）
 * @param score 相关性得分 0..1
 * @param scoreStage 得分阶段 dense/sparse/rrf/rerank（对外叫 {@code stage}）
 * @param kind 片段类型 chunk/summary/rule
 * @param verified 是否人工审核通过
 */
public record AiCitation(
        Object ref,
        String chunkId,
        String docId,
        String docTitle,
        String headingPath,
        String excerpt,
        Integer start,
        Integer end,
        Double score,
        String scoreStage,
        String kind,
        Boolean verified) {}
