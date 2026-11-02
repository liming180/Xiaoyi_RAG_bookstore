package com.xiaoyi.rag.model.dto;

import java.util.List;

/** 批量评测请求，对应 EvalBatchRequest。 */
public record EvalBatchRequest(List<String> questionIds, String mode, Integer k) {}
