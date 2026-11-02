package com.xiaoyi.rag.model.dto;

import java.util.List;

/** 资料更新请求：只允许改 title / tags / status（启停用）。 */
public record UpdateDocumentRequest(
        String title, List<String> tags, String version, String status) {}
