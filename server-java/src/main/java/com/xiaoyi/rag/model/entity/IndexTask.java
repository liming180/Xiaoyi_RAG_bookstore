package com.xiaoyi.rag.model.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;
import java.time.Instant;

/**
 * 建库任务表 index_task。
 *
 * <p>J2 只用它做两件事：① 判断「有没有未完成的建库任务」（删除资料时先把未完成任务置 FAILED）； ② 文档增删改后把最新任务标记为 {@code needs_rebuild}
 * 的依据。真正的建库执行在 J4。
 *
 * <p>{@code chunk_size} / {@code overlap} 在库里是 NOT NULL 且无默认值，插入时必须给。
 *
 * <p>状态值以对外契约为准：{@code PENDING/RUNNING/SUCCEEDED/FAILED}。J1 建表时实体里写的是 {@code SUCCESS}， 与契约的 {@code
 * SUCCEEDED} 差一个字母，前端 {@code knowledge.ts} 的白名单也只认 {@code SUCCEEDED}， 会在 J4 第一次真跑建库时把终态吞成 {@code
 * RUNNING}。
 */
@Entity
@Table(name = "index_task")
public class IndexTask {

    /** 未完成状态：这两个状态下的任务算「在跑」，需要先置 FAILED 才能删资料。 */
    public static final String STATUS_PENDING = "PENDING";

    public static final String STATUS_RUNNING = "RUNNING";
    public static final String STATUS_FAILED = "FAILED";
    public static final String STATUS_SUCCEEDED = "SUCCEEDED";

    /** 契约 IndexTaskStage 的五值白名单，Python 侧的原始 stage 必须先映射到这里。 */
    public static final String STAGE_PARSING = "parsing";

    public static final String STAGE_SPLITTING = "splitting";
    public static final String STAGE_EMBEDDING = "embedding";
    public static final String STAGE_SUMMARIZING = "summarizing";
    public static final String STAGE_DONE = "done";

    /** 轮询连续失败多少次才判 FAILED（手册 §J4：失败只重试，连续 30 次才终态）。 */
    public static final int MAX_POLL_FAILURES = 30;

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "status", nullable = false, length = 16)
    private String status;

    @Column(name = "stage", nullable = false, length = 16)
    private String stage;

    @Column(name = "progress", nullable = false)
    private Integer progress;

    @Column(name = "chunk_size", nullable = false)
    private Integer chunkSize;

    @Column(name = "overlap", nullable = false)
    private Integer overlap;

    /**
     * Python 侧 /documents/parse 返回的 task_id。
     *
     * <p>必须落库：轮询 /ingest/{external_task_id} 时靠它定位 Python 的任务；Java 自己的主键 id 是对外契约的 taskId，两者不是一个东西。
     */
    @Column(name = "external_task_id", length = 64)
    private String externalTaskId;

    @Column(name = "embedding_model", length = 64)
    private String embeddingModel;

    @Column(name = "doc_count", nullable = false)
    private Integer docCount;

    @Column(name = "chunk_count", nullable = false)
    private Integer chunkCount;

    @Column(name = "error", length = 512)
    private String error;

    /** 轮询连续失败次数；成功一次即归零。落库是为了让「连续 30 次」在服务重启后仍然成立。 */
    @Column(name = "poll_failures", nullable = false)
    private Integer pollFailures;

    @Column(name = "created_at", nullable = false)
    private Long createdAt;

    @Column(name = "finished_at")
    private Long finishedAt;

    public IndexTask() {
        // JPA 需要无参构造
    }

    @PrePersist
    void onCreate() {
        if (createdAt == null) {
            createdAt = Instant.now().getEpochSecond();
        }
        if (status == null || status.isBlank()) {
            status = STATUS_PENDING;
        }
        if (stage == null || stage.isBlank()) {
            stage = "parsing";
        }
        if (progress == null) {
            progress = 0;
        }
        if (docCount == null) {
            docCount = 0;
        }
        if (chunkCount == null) {
            chunkCount = 0;
        }
        if (pollFailures == null) {
            pollFailures = 0;
        }
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public String getStage() {
        return stage;
    }

    public void setStage(String stage) {
        this.stage = stage;
    }

    public Integer getProgress() {
        return progress;
    }

    public void setProgress(Integer progress) {
        this.progress = progress;
    }

    public Integer getChunkSize() {
        return chunkSize;
    }

    public void setChunkSize(Integer chunkSize) {
        this.chunkSize = chunkSize;
    }

    public Integer getOverlap() {
        return overlap;
    }

    public void setOverlap(Integer overlap) {
        this.overlap = overlap;
    }

    public String getEmbeddingModel() {
        return embeddingModel;
    }

    public void setEmbeddingModel(String embeddingModel) {
        this.embeddingModel = embeddingModel;
    }

    public String getExternalTaskId() {
        return externalTaskId;
    }

    public void setExternalTaskId(String externalTaskId) {
        this.externalTaskId = externalTaskId;
    }

    public Integer getPollFailures() {
        return pollFailures;
    }

    public void setPollFailures(Integer pollFailures) {
        this.pollFailures = pollFailures;
    }

    public Integer getDocCount() {
        return docCount;
    }

    public void setDocCount(Integer docCount) {
        this.docCount = docCount;
    }

    public Integer getChunkCount() {
        return chunkCount;
    }

    public void setChunkCount(Integer chunkCount) {
        this.chunkCount = chunkCount;
    }

    public String getError() {
        return error;
    }

    public void setError(String error) {
        this.error = error;
    }

    public Long getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Long createdAt) {
        this.createdAt = createdAt;
    }

    public Long getFinishedAt() {
        return finishedAt;
    }

    public void setFinishedAt(Long finishedAt) {
        this.finishedAt = finishedAt;
    }
}
