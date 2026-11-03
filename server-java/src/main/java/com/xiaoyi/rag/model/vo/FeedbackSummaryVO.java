package com.xiaoyi.rag.model.vo;

/** 当前反馈总量与待处理候选数。 */
public record FeedbackSummaryVO(long total, long up, long down, long candidates) {}
