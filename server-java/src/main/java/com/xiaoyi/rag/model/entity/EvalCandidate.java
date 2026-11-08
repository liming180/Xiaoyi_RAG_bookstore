package com.xiaoyi.rag.model.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;
import java.time.Instant;

/** 从反馈产生的评测候选；保留问题快照，避免会话删除影响候选池。 */
@Entity
@Table(name = "eval_candidate")
public class EvalCandidate {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "message_id", unique = true)
    private Long messageId;

    @Column(name = "question", nullable = false, columnDefinition = "MEDIUMTEXT")
    private String question;

    @Column(name = "source", nullable = false, length = 16)
    private String source;

    @Column(name = "status", nullable = false, length = 16)
    private String status;

    /**
     * 人工补的判分关键词，语法同 {@code assets/eval/keywords.csv}。
     *
     * <p>NULL / 空白 = 没补。没补不影响进实验，只影响计分：{@code metrics.scored} 里不算它，{@code hitRate} 的分母也不含它 ——
     * 没有关键词就判不出对错，硬判只会算出一个假分数。
     */
    @Column(name = "keywords", length = 512)
    private String keywords;

    @Column(name = "created_at", nullable = false)
    private Long createdAt;

    @PrePersist
    void onCreate() {
        if (createdAt == null) {
            createdAt = Instant.now().getEpochSecond();
        }
    }

    public Long getId() {
        return id;
    }

    public Long getMessageId() {
        return messageId;
    }

    public void setMessageId(Long messageId) {
        this.messageId = messageId;
    }

    public String getQuestion() {
        return question;
    }

    public void setQuestion(String question) {
        this.question = question;
    }

    public String getSource() {
        return source;
    }

    public void setSource(String source) {
        this.source = source;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public String getKeywords() {
        return keywords;
    }

    public void setKeywords(String keywords) {
        this.keywords = keywords;
    }

    public Long getCreatedAt() {
        return createdAt;
    }
}
