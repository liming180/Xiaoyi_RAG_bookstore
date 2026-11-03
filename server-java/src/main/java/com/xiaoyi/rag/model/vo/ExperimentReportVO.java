package com.xiaoyi.rag.model.vo;

import java.util.List;
import java.util.Map;

public record ExperimentReportVO(ExperimentVO experiment, List<Run> runs) {
    public record Run(
            String id, Map<String, Object> params, Map<String, Object> metrics, long elapsedMs) {}
}
