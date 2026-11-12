package com.xiaoyi.rag.model.vo;

import java.util.List;

/**
 * 管理端分页结果，形状对齐前端既有 {@code Page<T>}（{@code { items, total, page, size }}）。
 *
 * <p>不复用 Spring Data 的 {@code Page}：它的 JSON 会带 {@code pageable}、{@code sort}、 {@code first}/{@code
 * last} 等一大堆前端不认的字段，与契约 {@code additionalProperties: false} 冲突。
 */
public record AdminUserPageVO(List<AdminUserItemVO> items, long total, int page, int size) {}
