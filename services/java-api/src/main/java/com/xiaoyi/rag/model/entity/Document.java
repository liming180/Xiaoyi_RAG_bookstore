package com.xiaoyi.rag.model.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import jakarta.persistence.Version;
import java.time.Instant;

/**
 * 资料表 document。
 *
 * <p>表里没有 {@code enabled} 列：启停用语义直接映射到 {@code status}（{@code DISABLED} 即停用）， 与前端 {@code
 * frontend/src/api/modules/knowledge.ts} 的 {@code setDocumentEnabled} 一致。
 *
 * <p>{@code tags} 是 VARCHAR 逗号分隔，不是 JSON 列。
 */
@Entity
@Table(name = "document")
public class Document {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "title", nullable = false, length = 255)
    private String title;

    @Column(name = "filename", nullable = false, length = 255)
    private String filename;

    @Column(name = "storage_key", length = 512)
    private String storageKey;

    @Column(name = "sha256", length = 64)
    private String sha256;

    @Column(name = "version", nullable = false, length = 32)
    private String version;

    @Column(name = "tags", length = 512)
    private String tags;

    @Column(name = "status", nullable = false, length = 24)
    private String status;

    @Column(name = "verified", nullable = false)
    private Boolean verified;

    @Column(name = "char_count", nullable = false)
    private Integer charCount;

    @Column(name = "chunk_count", nullable = false)
    private Integer chunkCount;

    @Column(name = "error_msg", length = 512)
    private String errorMsg;

    @Column(name = "uploaded_by")
    private Long uploadedBy;

    /**
     * 乐观锁版本号。
     *
     * <p>建库成功时用它判断「这份资料从我拍快照到现在有没有被改过」：快照里带 revision，收尾时原子地 {@code where revision =
     * :snapshotRevision} 才落片段并把资料置 INDEXED，避免建库期间用户改了标题/正文却被静默覆盖。
     *
     * <p>注意：JPQL 批量 update 不会触发 {@code @Version}，所以 {@code markSnapshotIndexed} 里显式 {@code revision
     * = revision + 1}。
     */
    @Version
    @Column(name = "revision", nullable = false)
    private Long revision;

    @Column(name = "deleted", nullable = false)
    private Boolean deleted;

    @Column(name = "created_at", nullable = false)
    private Long createdAt;

    @Column(name = "updated_at", nullable = false)
    private Long updatedAt;

    public Document() {
        // JPA 需要无参构造
    }

    @PrePersist
    void onCreate() {
        long now = Instant.now().getEpochSecond();
        if (createdAt == null) {
            createdAt = now;
        }
        updatedAt = now;
        if (deleted == null) {
            deleted = false;
        }
        if (verified == null) {
            verified = true;
        }
        if (charCount == null) {
            charCount = 0;
        }
        if (chunkCount == null) {
            chunkCount = 0;
        }
        if (version == null || version.isBlank()) {
            version = "v1";
        }
        if (status == null || status.isBlank()) {
            status = "UPLOADING";
        }
    }

    @PreUpdate
    void onUpdate() {
        updatedAt = Instant.now().getEpochSecond();
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getTitle() {
        return title;
    }

    public void setTitle(String title) {
        this.title = title;
    }

    public String getFilename() {
        return filename;
    }

    public void setFilename(String filename) {
        this.filename = filename;
    }

    public String getStorageKey() {
        return storageKey;
    }

    public void setStorageKey(String storageKey) {
        this.storageKey = storageKey;
    }

    public String getSha256() {
        return sha256;
    }

    public void setSha256(String sha256) {
        this.sha256 = sha256;
    }

    public String getVersion() {
        return version;
    }

    public void setVersion(String version) {
        this.version = version;
    }

    public String getTags() {
        return tags;
    }

    public void setTags(String tags) {
        this.tags = tags;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public Boolean getVerified() {
        return verified;
    }

    public void setVerified(Boolean verified) {
        this.verified = verified;
    }

    public Integer getCharCount() {
        return charCount;
    }

    public void setCharCount(Integer charCount) {
        this.charCount = charCount;
    }

    public Integer getChunkCount() {
        return chunkCount;
    }

    public void setChunkCount(Integer chunkCount) {
        this.chunkCount = chunkCount;
    }

    public String getErrorMsg() {
        return errorMsg;
    }

    public void setErrorMsg(String errorMsg) {
        this.errorMsg = errorMsg;
    }

    public Long getRevision() {
        return revision;
    }

    public void setRevision(Long revision) {
        this.revision = revision;
    }

    public Long getUploadedBy() {
        return uploadedBy;
    }

    public void setUploadedBy(Long uploadedBy) {
        this.uploadedBy = uploadedBy;
    }

    public Boolean getDeleted() {
        return deleted;
    }

    public void setDeleted(Boolean deleted) {
        this.deleted = deleted;
    }

    public Long getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Long createdAt) {
        this.createdAt = createdAt;
    }

    public Long getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(Long updatedAt) {
        this.updatedAt = updatedAt;
    }
}
