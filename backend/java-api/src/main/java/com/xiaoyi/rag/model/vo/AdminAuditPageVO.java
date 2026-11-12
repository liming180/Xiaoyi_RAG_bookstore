package com.xiaoyi.rag.model.vo;

import java.util.List;

/**
 * 管理端审计分页结果，形状与用户管理列表一致（{@code { items, total, page, size }}）。
 *
 * <p>复用同一种分页信封是刻意的：前端分页组件、空态文案、loading 逻辑可以完全共用一套。
 */
public record AdminAuditPageVO(List<AdminAuditItemVO> items, long total, int page, int size) {}
