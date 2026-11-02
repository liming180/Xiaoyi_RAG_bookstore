package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.common.interceptor.AuthInterceptor;
import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.model.dto.UpdateDocumentRequest;
import com.xiaoyi.rag.model.vo.DocumentVO;
import com.xiaoyi.rag.model.vo.UploadResultVO;
import com.xiaoyi.rag.service.DocumentService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.util.List;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

/**
 * 知识库：5 条对外接口（J2 实现前 4 条，{@code listChunks} 属 J4）。
 *
 * <p>operationId：listDocuments / uploadDocuments / updateDocument / deleteDocument / listChunks。
 */
@RestController
@RequestMapping("/api/v1")
@Tag(name = "知识库")
public class KnowledgeController {

    private final DocumentService documentService;

    public KnowledgeController(DocumentService documentService) {
        this.documentService = documentService;
    }

    @GetMapping("/documents")
    @Operation(operationId = "listDocuments", summary = "资料列表")
    public Result<List<DocumentVO>> listDocuments() {
        return Result.ok(documentService.list());
    }

    /**
     * multipart 字段名必须是 files，与 frontend/src/api/modules/knowledge.ts 一致。
     *
     * <p>{@code files} 缺失或全为空是唯一会让整批失败的情况（40001，见 error-codes.md §12）； 单份文件不合规只进 {@code
     * data.skipped[]}。
     */
    @PostMapping(value = "/documents", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    @Operation(operationId = "uploadDocuments", summary = "上传资料（可多文件）")
    public Result<UploadResultVO> uploadDocuments(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId,
            @RequestPart(name = "files", required = false) List<MultipartFile> files) {
        if (files == null || files.isEmpty()) {
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "请至少上传一个文件（字段名 files）");
        }
        return Result.ok(documentService.upload(files, userId == null ? 1L : userId));
    }

    @PutMapping("/documents/{id}")
    @Operation(operationId = "updateDocument", summary = "改标题 / 标签 / 启停用")
    public Result<DocumentVO> updateDocument(
            @PathVariable String id, @RequestBody(required = false) UpdateDocumentRequest request) {
        return Result.ok(documentService.update(parseId(id), request));
    }

    @DeleteMapping("/documents/{id}")
    @Operation(operationId = "deleteDocument", summary = "删除资料")
    public Result<Void> deleteDocument(@PathVariable String id) {
        documentService.delete(parseId(id));
        return Result.ok();
    }

    @GetMapping("/chunks")
    @Operation(operationId = "listChunks", summary = "片段列表，可按 docId / q / kind 过滤")
    public Result<Object> listChunks(
            @RequestParam(required = false) String docId,
            @RequestParam(required = false) String q,
            @RequestParam(required = false) String kind) {
        // J4 建库后才有片段可列，J2 保持未实现。
        throw new ApiException(ErrorCode.NOT_IMPLEMENTED.getCode(), "尚未实现");
    }

    /**
     * 路径 id 转 {@code Long}。契约里 id 是双形状，非数字一律当「不存在」， 交给 Service 抛 40401，避免变成 500。
     *
     * @param raw 路径上的 id
     * @return 解析后的 id；无法解析时返回 {@code -1}
     */
    private Long parseId(String raw) {
        try {
            return Long.valueOf(raw);
        } catch (NumberFormatException ex) {
            return -1L;
        }
    }
}
