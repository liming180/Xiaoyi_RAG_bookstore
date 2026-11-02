package com.xiaoyi.rag.model.vo;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.List;

/**
 * 资料视图，对应契约 {@code components.schemas.DocumentMeta}。
 *
 * <p>契约 required：{@code [id, name, title, tags, version, charCount, chunkCount, status, verified,
 * updatedAt]}， {@code additionalProperties: false}。注意契约字段名是 {@code name}（含后缀的文件名），**不是 filename**。
 *
 * @param id 资料 id
 * @param name 原文件名（含后缀）
 * @param title 展示标题，默认取正文首个一级标题，取不到回落 name
 * @param tags 标签数组（库里是逗号分隔字符串，出参时拆开）
 * @param version 版本号，如 v1
 * @param charCount 正文字符数
 * @param chunkCount 片段数（J4 建库后才有值）
 * @param status UPLOADING / PARSING / INDEXED / FAILED / NEEDS_REBUILD / DISABLED
 * @param verified 是否人工审核通过
 * @param updatedAt 更新时间（Unix 秒）
 * @param error 失败原因，正常为 null 且不输出
 */
public record DocumentVO(
        String id,
        String name,
        String title,
        List<String> tags,
        String version,
        Integer charCount,
        Integer chunkCount,
        String status,
        Boolean verified,
        Long updatedAt,
        @JsonInclude(JsonInclude.Include.NON_NULL) String error) {}
