package com.xiaoyi.rag.model.vo;

import java.util.List;

/**
 * 上传结果，对应契约 {@code components.schemas.UploadResult}。
 *
 * <p>整体仍是成功信封 {@code {code: 0}}：个别文件不合规进 {@code skipped}，不影响整批 （{@code docs/api/error-codes.md}
 * §12「上传的非错误通道」）。只有 {@code files} 字段缺失或全空 才由 Controller 抛 {@code 40001}。
 *
 * @param accepted 已收下的资料
 * @param skipped 被拒收的文件及中文原因
 */
public record UploadResultVO(List<DocumentVO> accepted, List<UploadSkippedVO> skipped) {}
