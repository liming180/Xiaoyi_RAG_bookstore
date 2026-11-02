package com.xiaoyi.rag.model.dto;

import java.util.List;

/** 创建参数实验请求，对应 CreateExperimentRequest。 */
public record CreateExperimentRequest(String name, ExperimentAxis axes) {

    /** 参数矩阵的每一根轴。 */
    public record ExperimentAxis(
            List<Integer> chunkSize,
            List<Integer> overlap,
            List<Integer> k,
            List<Boolean> rerank,
            List<Boolean> summary) {}
}
