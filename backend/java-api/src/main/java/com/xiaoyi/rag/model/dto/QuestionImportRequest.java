package com.xiaoyi.rag.model.dto;

/**
 * 题库 CSV 导入请求。
 *
 * <p>为什么把正文放 JSON 里而不是 multipart：导入的是一段纯文本，几十行量级， 用 multipart 反而要额外处理 boundary 与编码；JSON
 * 正文最直接，也和导出端点对称（导出是 text/csv，导回时前端读文本再包一层 JSON）。
 *
 * @param csv CSV 正文，列序「题号,类型,问题,关键词,证据文件」，表头可省略
 */
public record QuestionImportRequest(String csv) {}
