package com.xiaoyi.rag.model.vo;

import java.util.List;
import java.util.Map;

public record EvalRunVO(
        String id,
        long createdAt,
        Long finishedAt,
        String status,
        int progress,
        Map<String, Integer> stats,
        String mode,
        int k,
        List<EvalCaseResultVO> cases) {}
