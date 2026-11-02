package com.xiaoyi.rag.client.dto;

import java.util.List;

/**
 * 触发入库的请求，对应内部契约 {@code InternalParseRequest}。
 *
 * <p>{@code chunkSize} / {@code overlap} 必须如实带给 Python 并落进它的 manifest —— Java 侧 {@code
 * /index/status} 的 needs_rebuild 判定要拿「当前生效参数」和「manifest 里的参数」比对，两边不一致就说明有人改了参数没重建。
 */
public record AiParseRequest(
        List<AiParseDocumentItem> documents, Integer chunkSize, Integer overlap) {}
