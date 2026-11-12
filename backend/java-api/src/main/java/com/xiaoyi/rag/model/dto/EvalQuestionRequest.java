package com.xiaoyi.rag.model.dto;

/**
 * 新增 / 修改题目的请求。
 *
 * @param code 题号；新增时留空会自动按题型生成
 * @param type single / cross / out
 * @param question 题面
 * @param keywords 判分关键词，语法同 keywords.csv（组内 {@code /} 同义、组间 {@code |} 必须全中）；空串 = 不参与计分
 * @param evidence 证据文件名，库外题填「无」或留空
 */
public record EvalQuestionRequest(
        String code, String type, String question, String keywords, String evidence) {}
