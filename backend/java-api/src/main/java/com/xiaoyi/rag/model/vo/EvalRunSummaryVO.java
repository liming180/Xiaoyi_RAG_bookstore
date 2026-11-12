package com.xiaoyi.rag.model.vo;

import java.util.Map;

public record EvalRunSummaryVO(
        String id,
        long createdAt,
        Long finishedAt,
        String status,
        int progress,
        Map<String, Integer> stats,
        String mode,
        int k) {
    public static EvalRunSummaryVO from(EvalRunVO run) {
        return new EvalRunSummaryVO(
                run.id(),
                run.createdAt(),
                run.finishedAt(),
                run.status(),
                run.progress(),
                run.stats(),
                run.mode(),
                run.k());
    }
}
