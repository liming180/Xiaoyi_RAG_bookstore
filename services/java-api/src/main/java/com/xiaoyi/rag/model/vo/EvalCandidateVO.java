package com.xiaoyi.rag.model.vo;

/**
 * 对外候选契约，对应 CandidateDecisionRequest 的反向视图。
 *
 * @param id 候选 id（字符串，与其它资源 id 一致）
 * @param question 问题快照
 * @param source feedback / manual
 * @param status pending / accepted / ignored
 * @param createdAt Unix 秒
 * @param keywords 人工补的判分关键词；{@code null} = 未补，进实验后不计分
 */
public record EvalCandidateVO(
        String id,
        String question,
        String source,
        String status,
        long createdAt,
        String keywords) {}
