package com.xiaoyi.rag.service.impl;

import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.model.dto.UpdateDocumentRequest;
import com.xiaoyi.rag.model.entity.Document;
import com.xiaoyi.rag.model.entity.IndexTask;
import com.xiaoyi.rag.model.vo.DocumentVO;
import com.xiaoyi.rag.model.vo.UploadResultVO;
import com.xiaoyi.rag.model.vo.UploadSkippedVO;
import com.xiaoyi.rag.repository.DocumentRepository;
import com.xiaoyi.rag.repository.IndexTaskRepository;
import com.xiaoyi.rag.service.DocumentService;
import com.xiaoyi.rag.service.Storage;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CharsetDecoder;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

/**
 * 知识库资料实现。
 *
 * <p>五道校验按「先廉价后昂贵」排：后缀 → 大小 → 解码 → 正文非空，任一不过就进 {@code skipped} 并继续下一份文件，绝不让单个坏文件拖垮整批（手册 §6）。
 *
 * <p>四个 {@code reason} 文案与 {@code docs/api/error-codes.md} §12 逐字一致，不得改写。
 *
 * <p>路径穿越：先按 {@code Path#getFileName()} 截末段再校验（error-codes.md §12「不报错」）， 落盘时 {@link
 * LocalStorage#store} 里还有一道 {@code startsWith(root)} 兜底。
 *
 * <p>H2 隔离：所有读写都带 {@code userId}。别人的资料一律当作不存在（{@code 40401}），不区分「无权限」和「没有」， 避免用状态码枚举他人资料
 * id。去重也只在本人范围内做 —— 同一份正文被两个用户分别上传，各存一份，互不可见。
 */
@Service
public class DocumentServiceImpl implements DocumentService {

    private static final Logger log = LoggerFactory.getLogger(DocumentServiceImpl.class);

    /** 业务上限：2MB。注意 Spring 的 multipart 传输上限被刻意设得更高，好让超限文件落到 skipped。 */
    private static final long MAX_BYTES = 2L * 1024 * 1024;

    /** 允许的后缀。 */
    private static final List<String> ALLOWED_EXT = List.of(".md", ".txt");

    private static final String REASON_EXT = "只接受 .md / .txt 文件";

    private static final String REASON_SIZE = "文件超过 2MB";

    private static final String REASON_EMPTY = "文件没有正文";

    private static final String REASON_ENCODING = "文件编码不是 UTF-8";

    /** 取正文首个一级标题作为默认 title。 */
    private static final Pattern FIRST_H1 =
            Pattern.compile("^#[ \\t]+(.+?)[ \\t]*$", Pattern.MULTILINE);

    /** 标题长度上限，与 document.title VARCHAR(255) 对齐。 */
    private static final int MAX_TITLE_LEN = 255;

    private final DocumentRepository documentRepository;

    private final IndexTaskRepository indexTaskRepository;

    private final Storage storage;

    public DocumentServiceImpl(
            DocumentRepository documentRepository,
            IndexTaskRepository indexTaskRepository,
            Storage storage) {
        this.documentRepository = documentRepository;
        this.indexTaskRepository = indexTaskRepository;
        this.storage = storage;
    }

    @Override
    @Transactional(readOnly = true)
    public List<DocumentVO> list(Long userId) {
        List<Document> rows =
                documentRepository.findByUploadedByAndDeletedFalseOrderByUpdatedAtDescIdDesc(
                        userId);
        List<DocumentVO> result = new ArrayList<>(rows.size());
        for (Document row : rows) {
            result.add(toVO(row));
        }
        return result;
    }

    @Override
    @Transactional
    public UploadResultVO upload(List<MultipartFile> files, Long userId) {
        List<DocumentVO> accepted = new ArrayList<>();
        List<UploadSkippedVO> skipped = new ArrayList<>();
        for (MultipartFile file : files) {
            if (file == null) {
                continue;
            }
            String original = file.getOriginalFilename();
            String shown = original == null ? "" : original;
            String filename = safeFilename(original);
            if (filename == null) {
                skipped.add(new UploadSkippedVO(shown, REASON_EXT));
                continue;
            }
            String lower = filename.toLowerCase(Locale.ROOT);
            if (ALLOWED_EXT.stream().noneMatch(lower::endsWith)) {
                skipped.add(new UploadSkippedVO(shown, REASON_EXT));
                continue;
            }
            if (file.getSize() > MAX_BYTES) {
                skipped.add(new UploadSkippedVO(shown, REASON_SIZE));
                continue;
            }
            byte[] bytes;
            try {
                bytes = file.getBytes();
            } catch (IOException ex) {
                log.warn("读取上传文件失败：{} - {}", shown, ex.getMessage());
                skipped.add(new UploadSkippedVO(shown, REASON_EMPTY));
                continue;
            }
            if (bytes.length > MAX_BYTES) {
                skipped.add(new UploadSkippedVO(shown, REASON_SIZE));
                continue;
            }
            String text;
            try {
                text = decodeUtf8(bytes);
            } catch (CharacterCodingException ex) {
                skipped.add(new UploadSkippedVO(shown, REASON_ENCODING));
                continue;
            }
            if (text.isBlank()) {
                skipped.add(new UploadSkippedVO(shown, REASON_EMPTY));
                continue;
            }
            String sha256 = sha256Hex(bytes);
            Optional<Document> duplicated =
                    documentRepository.findFirstBySha256AndUploadedByAndDeletedFalse(
                            sha256, userId);
            if (duplicated.isPresent()) {
                // 本人已收过同一份内容：不重复落盘，直接把已有记录回给前端（sha256 去重，按用户隔离）。
                accepted.add(toVO(duplicated.get()));
                continue;
            }
            Document entity = new Document();
            entity.setFilename(filename);
            entity.setTitle(resolveTitle(text, filename));
            entity.setSha256(sha256);
            entity.setVersion("v1");
            entity.setStatus("UPLOADING");
            entity.setVerified(true);
            entity.setCharCount(text.length());
            entity.setChunkCount(0);
            entity.setUploadedBy(userId);
            entity.setDeleted(false);
            Document saved = documentRepository.save(entity);
            try {
                String storageKey = storage.store(saved.getId(), filename, bytes);
                saved.setStorageKey(storageKey);
            } catch (IOException ex) {
                log.error("落盘失败，回滚该文件的入库：{} - {}", filename, ex.getMessage());
                documentRepository.delete(saved);
                skipped.add(new UploadSkippedVO(shown, REASON_EMPTY));
                continue;
            }
            documentRepository.save(saved);
            accepted.add(toVO(saved));
        }
        if (!accepted.isEmpty()) {
            markNeedsRebuild(userId);
        }
        return new UploadResultVO(accepted, skipped);
    }

    @Override
    @Transactional
    public DocumentVO update(Long userId, Long documentId, UpdateDocumentRequest request) {
        Document entity = requireDocument(userId, documentId);
        if (request != null) {
            if (request.title() != null && !request.title().isBlank()) {
                entity.setTitle(truncate(request.title().trim()));
            }
            if (request.tags() != null) {
                entity.setTags(String.join(",", request.tags()));
            }
            if (request.version() != null && !request.version().isBlank()) {
                entity.setVersion(request.version().trim());
            }
            if (request.status() != null && !request.status().isBlank()) {
                entity.setStatus(request.status().trim());
            }
        }
        Document saved = documentRepository.save(entity);
        markNeedsRebuild(userId);
        return toVO(saved);
    }

    @Override
    @Transactional
    public void delete(Long userId, Long documentId) {
        Document entity = requireDocument(userId, documentId);
        // 手册 §6：有未完成任务时先置 FAILED 再删。只中止本人任务，别把别人的建库打断。
        List<IndexTask> running =
                indexTaskRepository.findByUserIdAndStatusInOrderByCreatedAtDesc(
                        userId, List.of(IndexTask.STATUS_PENDING, IndexTask.STATUS_RUNNING));
        for (IndexTask task : running) {
            task.setStatus(IndexTask.STATUS_FAILED);
            task.setError("资料已删除，建库任务中止");
            task.setFinishedAt(Instant.now().getEpochSecond());
            indexTaskRepository.save(task);
        }
        try {
            storage.deleteByDocumentId(entity.getId());
        } catch (IOException ex) {
            log.warn("删除磁盘文件失败（继续删元数据）：{} - {}", entity.getId(), ex.getMessage());
        }
        documentRepository.softDeleteByIdAndUploadedBy(entity.getId(), userId);
        markNeedsRebuild(userId);
    }

    @Override
    public String storageRoot() {
        return storage.rootPath();
    }

    /**
     * 语料变了就把该用户已建好的索引标脏。
     *
     * <p>库里没有独立 index_status 列，故直接从 document 状态推导（手册 §6 第 5 条允许这种推导）。
     *
     * @param userId 归属人
     */
    private void markNeedsRebuild(Long userId) {
        int touched = documentRepository.markIndexedAsNeedsRebuild(userId);
        if (touched > 0) {
            log.debug("用户 {} 的 {} 份资料索引已标脏为 NEEDS_REBUILD", userId, touched);
        }
    }

    /**
     * 取本人资料，不存在、已软删或属于别人都抛 {@code 40401}。
     *
     * @param userId 归属人
     * @param documentId 资料 id
     * @return 资料实体
     */
    private Document requireDocument(Long userId, Long documentId) {
        return documentRepository
                .findByIdAndUploadedByAndDeletedFalse(documentId, userId)
                .orElseThrow(
                        () ->
                                new ApiException(
                                        ErrorCode.DOCUMENT_NOT_FOUND.getCode(),
                                        ErrorCode.DOCUMENT_NOT_FOUND.getDefaultMessage()));
    }

    /**
     * 取纯文件名：只留最后一段，丢掉任何目录成分。
     *
     * @param original 原始文件名，可为 null
     * @return 纯文件名；无法提取时返回 null
     */
    private String safeFilename(String original) {
        if (original == null || original.isBlank()) {
            return null;
        }
        String normalized = original.replace('\\', '/');
        int slash = normalized.lastIndexOf('/');
        String name = slash >= 0 ? normalized.substring(slash + 1) : normalized;
        return name.isBlank() ? null : name;
    }

    /**
     * 严格按 UTF-8 解码，非法字节直接抛异常（而不是替换成 U+FFFD）。
     *
     * @param bytes 原始字节
     * @return 文本
     */
    private String decodeUtf8(byte[] bytes) throws CharacterCodingException {
        CharsetDecoder decoder =
                StandardCharsets.UTF_8
                        .newDecoder()
                        .onMalformedInput(CodingErrorAction.REPORT)
                        .onUnmappableCharacter(CodingErrorAction.REPORT);
        return decoder.decode(ByteBuffer.wrap(bytes)).toString();
    }

    /**
     * 计算 sha256 十六进制小写串。
     *
     * @param bytes 原始字节
     * @return 64 位十六进制
     */
    private String sha256Hex(byte[] bytes) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(bytes));
        } catch (NoSuchAlgorithmException ex) {
            // SHA-256 是 JDK 必备算法，走到这里说明运行环境被裁剪过。
            throw new IllegalStateException("JVM 缺少 SHA-256 实现", ex);
        }
    }

    /**
     * 取正文首个一级标题作为标题，取不到回落文件名（手册 §6「filename 与 title 分离」）。
     *
     * @param text 正文
     * @param filename 纯文件名
     * @return 标题
     */
    private String resolveTitle(String text, String filename) {
        Matcher matcher = FIRST_H1.matcher(text);
        if (matcher.find()) {
            String heading = matcher.group(1).trim();
            if (!heading.isEmpty()) {
                return truncate(heading);
            }
        }
        return truncate(filename);
    }

    /**
     * 截断到列宽上限。
     *
     * @param value 原文
     * @return 不超过 {@value #MAX_TITLE_LEN} 个字符的串
     */
    private String truncate(String value) {
        return value.length() <= MAX_TITLE_LEN ? value : value.substring(0, MAX_TITLE_LEN);
    }

    /**
     * 实体转视图。
     *
     * @param entity 实体
     * @return 视图
     */
    private DocumentVO toVO(Document entity) {
        List<String> tags =
                entity.getTags() == null || entity.getTags().isBlank()
                        ? List.of()
                        : Arrays.stream(entity.getTags().split(","))
                                .map(String::trim)
                                .filter(item -> !item.isEmpty())
                                .toList();
        return new DocumentVO(
                String.valueOf(entity.getId()),
                entity.getFilename(),
                entity.getTitle(),
                tags,
                entity.getVersion(),
                entity.getCharCount(),
                entity.getChunkCount(),
                entity.getStatus(),
                Boolean.TRUE.equals(entity.getVerified()),
                entity.getUpdatedAt(),
                entity.getErrorMsg());
    }
}
