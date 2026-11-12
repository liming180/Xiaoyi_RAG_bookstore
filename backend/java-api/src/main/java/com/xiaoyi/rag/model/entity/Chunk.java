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
 * 片段缓存表 chunk —— {@code GET /api/v1/chunks} 的数据来源。
 *
 * <p>为什么 Java 侧存一份而不是每次问 Python（手册 §J4 第 4 条二选一）：
 *
 * <ul>
 *   <li>Python 侧任务表是进程内 dict，重启即丢；片段浏览页要求重启后仍看得到上次建库结果。
 *   <li>片段浏览是纯读、无检索语义，走 Python 的 list 模式等于为一个分页查询付一次 HTTP + 服务可用性代价。
 * </ul>
 *
 * <p>代价是「以最后一次成功建库为准」：建库成功时整表替换。这也正是 {@code /index/status} 的 needs_rebuild 语义 所依赖的 ——
 * 参数变了但没重建，缓存还是旧的。
 *
 * <p>列名 {@code char_start} / {@code char_end} 而非 {@code start} / {@code end}：{@code END} 是 MySQL
 * 保留字。
 */
@Entity
@Table(name = "chunk")
public class Chunk {

    /** 片段类型白名单，与契约 ChunkKind 一致。 */
    public static final String KIND_CHUNK = "chunk";

    public static final String KIND_SUMMARY = "summary";
    public static final String KIND_RULE = "rule";

    /**
     * 摘要卡的 `doc_id` 哨兵值（N3）。
     *
     * <p>摘要卡属于「全库」而不是任何一份资料，Python 侧给的是 {@code "__summary__"}；但 `chunk.doc_id` 是 `BIGINT NOT
     * NULL`，存不了字符串。折中：库里统一存 0，对外输出时 再翻回 `"__summary__"`（见 `IndexServiceImpl.listChunks`）。
     *
     * <p>为什么不用 `NULL`：列是 NOT NULL，且「0 = 全库摘要」是个确定语义，比 NULL 更好查。 为什么不用一个真的资料
     * id：那会让摘要卡在「删除该资料」时被连带清掉。
     */
    public static final long SUMMARY_DOC_ID = 0L;

    /** 摘要卡对外暴露的 docId 字面量。 */
    public static final String SUMMARY_DOC_LABEL = "__summary__";

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 产出它的建库任务。 */
    @Column(name = "task_id", nullable = false)
    private Long taskId;

    /**
     * 片段归属的用户，冗余自 {@code index_task.user_id}。
     *
     * <p>冗余一列而不是每次 join 任务表：片段浏览、按用户计数、按用户整代替换都是热路径，join 一次要多扫一张表；
     * 而片段只会随任务成功一次性写入，不存在「改了任务但片段没跟上」的窗口。
     */
    @Column(name = "user_id")
    private Long userId;

    /** 片段号，形如 {@code D02-C001}；对外契约里有 {@code ^D\d{2}-C\d{3}$} 的模式约束。 */
    @Column(name = "chunk_id", nullable = false, length = 32)
    private String chunkId;

    @Column(name = "doc_id", nullable = false)
    private Long docId;

    @Column(name = "doc_title", nullable = false, length = 255)
    private String docTitle;

    @Column(name = "heading_path", nullable = false, length = 512)
    private String headingPath;

    @Column(name = "text", nullable = false, columnDefinition = "MEDIUMTEXT")
    private String text;

    @Column(name = "char_start", nullable = false)
    private Integer start;

    @Column(name = "char_end", nullable = false)
    private Integer end;

    @Column(name = "kind", nullable = false, length = 16)
    private String kind;

    @Column(name = "verified", nullable = false)
    private Boolean verified;

    /** 全局序号，保证 {@code index} 字段在多任务、多资料下仍稳定递增。 */
    @Column(name = "seq", nullable = false)
    private Integer seq;

    @Column(name = "created_at", nullable = false)
    private Long createdAt;

    public Chunk() {
        // JPA 需要无参构造
    }

    @PrePersist
    void onCreate() {
        if (createdAt == null) {
            createdAt = Instant.now().getEpochSecond();
        }
        if (kind == null || kind.isBlank()) {
            kind = KIND_CHUNK;
        }
        if (verified == null) {
            verified = true;
        }
        if (start == null) {
            start = 0;
        }
        if (end == null) {
            end = 0;
        }
        if (seq == null) {
            seq = 0;
        }
        if (docTitle == null) {
            docTitle = "";
        }
        if (headingPath == null) {
            headingPath = "";
        }
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public Long getTaskId() {
        return taskId;
    }

    public void setTaskId(Long taskId) {
        this.taskId = taskId;
    }

    public Long getUserId() {
        return userId;
    }

    public void setUserId(Long userId) {
        this.userId = userId;
    }

    public String getChunkId() {
        return chunkId;
    }

    public void setChunkId(String chunkId) {
        this.chunkId = chunkId;
    }

    public Long getDocId() {
        return docId;
    }

    public void setDocId(Long docId) {
        this.docId = docId;
    }

    public String getDocTitle() {
        return docTitle;
    }

    public void setDocTitle(String docTitle) {
        this.docTitle = docTitle;
    }

    public String getHeadingPath() {
        return headingPath;
    }

    public void setHeadingPath(String headingPath) {
        this.headingPath = headingPath;
    }

    public String getText() {
        return text;
    }

    public void setText(String text) {
        this.text = text;
    }

    public Integer getStart() {
        return start;
    }

    public void setStart(Integer start) {
        this.start = start;
    }

    public Integer getEnd() {
        return end;
    }

    public void setEnd(Integer end) {
        this.end = end;
    }

    public String getKind() {
        return kind;
    }

    public void setKind(String kind) {
        this.kind = kind;
    }

    public Boolean getVerified() {
        return verified;
    }

    public void setVerified(Boolean verified) {
        this.verified = verified;
    }

    public Integer getSeq() {
        return seq;
    }

    public void setSeq(Integer seq) {
        this.seq = seq;
    }

    public Long getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Long createdAt) {
        this.createdAt = createdAt;
    }
}
