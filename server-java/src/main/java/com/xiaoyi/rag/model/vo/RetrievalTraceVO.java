package com.xiaoyi.rag.model.vo;

import java.util.List;

/**
 * 检索轨迹，对应契约 {@code components.schemas.RetrievalTrace}。
 *
 * <p>required 5 项、{@code additionalProperties: false}。{@code k} 上限 10、{@code chunkSize} 50..1000
 * 由契约约束，这里不做二次校验 —— 值来自建库 manifest 与请求参数，写进来之前已各自校验过。
 *
 * @param question 改写后的查询
 * @param k 召回条数
 * @param chunkSize 建库时的片段长度
 * @param overlap 建库时的重叠字数
 * @param rows 候选行（含未进入 top-k 的）
 */
public record RetrievalTraceVO(
        String question, Integer k, Integer chunkSize, Integer overlap, List<TraceRowVO> rows) {}
