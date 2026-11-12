package com.xiaoyi.rag.model.vo;

/**
 * 被拒收的文件，对应契约 {@code components.schemas.UploadSkipped}。
 *
 * <p>{@code reason} 必须是中文，且四类固定文案与 {@code docs/api/error-codes.md} §12 逐字一致， 前端 {@code
 * frontend/src/api/modules/knowledge.ts} 直接把它展示给用户。
 *
 * @param name 原始文件名
 * @param reason 拒收原因（中文）
 */
public record UploadSkippedVO(String name, String reason) {}
