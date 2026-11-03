package com.xiaoyi.rag.model.vo;

public record EvalQuestionVO(
        String id, String type, String question, String keywords, String evidence) {}
