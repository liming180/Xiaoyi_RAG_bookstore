package com.xiaoyi.rag.model.dto;

import java.util.List;

/**
 * 创建参数实验请求，对应 CreateExperimentRequest。
 *
 * @param name 实验名；空则落「参数实验」
 * @param questionIds 选题。空 = 全部 13 道题库题；`T01`–`T13` 走题库，`C<候选id>` 走候选池
 * @param axes 参数矩阵的每一根轴
 */
public record CreateExperimentRequest(String name, List<String> questionIds, ExperimentAxis axes) {

    /** 兼容旧调用：不选题 = 全题库。 */
    public CreateExperimentRequest(String name, ExperimentAxis axes) {
        this(name, List.of(), axes);
    }

    /** 参数矩阵的每一根轴。 */
    public record ExperimentAxis(
            List<Integer> chunkSize,
            List<Integer> overlap,
            List<Integer> k,
            List<Boolean> rerank,
            List<Boolean> summary) {}
}
