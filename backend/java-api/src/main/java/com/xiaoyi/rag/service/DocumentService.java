package com.xiaoyi.rag.service;

import com.xiaoyi.rag.model.dto.UpdateDocumentRequest;
import com.xiaoyi.rag.model.vo.DocumentVO;
import com.xiaoyi.rag.model.vo.UploadResultVO;
import java.util.List;
import org.springframework.web.multipart.MultipartFile;

/**
 * 知识库资料的业务接口（J2 的 4 条对外接口，{@code listChunks} 属 J4）。
 *
 * <p>上传是同步的：只做校验 + 落盘 + 落库，解析与切分是 J4 的异步任务。
 *
 * <p>每个方法都带 {@code userId}：资料按 {@code uploaded_by} 归属，跨用户一律按「不存在」处理。
 */
public interface DocumentService {

    /**
     * 该用户的资料列表，按 {@code updatedAt} 倒序。
     *
     * @param userId 归属人
     * @return 资料视图列表
     */
    List<DocumentVO> list(Long userId);

    /**
     * 上传资料（可多文件）。不合规文件进 {@code skipped}，不中断整批。
     *
     * @param files multipart 文件列表，Controller 已保证非空
     * @param userId 上传者
     * @return 收下的与拒收的
     */
    UploadResultVO upload(List<MultipartFile> files, Long userId);

    /**
     * 改标题 / 标签 / 版本 / 状态。{@code status=DISABLED} 等价于停用。
     *
     * @param userId 归属人
     * @param documentId 资料 id
     * @param request 请求体，可为 null（此时原样返回）
     * @return 更新后的资料视图
     */
    DocumentVO update(Long userId, Long documentId, UpdateDocumentRequest request);

    /**
     * 删除资料：置本人未完成任务为 FAILED，删元数据（软删），删磁盘文件。
     *
     * @param userId 归属人
     * @param documentId 资料 id
     */
    void delete(Long userId, Long documentId);

    /**
     * 存储根目录绝对路径，供测试断言磁盘上真的写出了文件。
     *
     * @return 绝对路径
     */
    String storageRoot();
}
