package com.xiaoyi.rag.client.dto;

import java.util.List;

/**
 * 提交给 Python 的一份待入库资料，对应内部契约 {@code ParseDocumentItem}。
 *
 * <p>{@code text} 是 Java 已按 UTF-8 严格解码后的正文，Python 不再做编码猜测 —— 编码判定 已经在 J2 上传时做过，重复做只会让两处规则不一致。
 */
public record AiParseDocumentItem(
        String docId, String name, String title, String text, List<String> tags, String version) {}
