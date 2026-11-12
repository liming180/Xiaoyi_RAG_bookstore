package com.xiaoyi.rag.model.dto;

/**
 * 停用 / 启用题目的请求。
 *
 * @param enabled true = 启用参与选题，false = 停用（历史评测仍可读）
 */
public record QuestionEnabledRequest(Boolean enabled) {}
