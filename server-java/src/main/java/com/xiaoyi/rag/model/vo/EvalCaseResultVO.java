package com.xiaoyi.rag.model.vo;

import java.util.List;

public record EvalCaseResultVO(
        String questionId,
        String type,
        String question,
        String directAnswer,
        boolean directPassed,
        String ragAnswer,
        boolean ragPassed,
        List<String> ragSources,
        long elapsedMs) {}
