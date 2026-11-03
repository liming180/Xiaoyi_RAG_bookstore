package com.xiaoyi.rag.model.vo;

/** 对外候选契约；隐藏关联消息 ID。 */
public record EvalCandidateVO(
        String id, String question, String source, String status, long createdAt) {}
