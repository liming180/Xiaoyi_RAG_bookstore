package com.xiaoyi.rag.model.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import java.time.Instant;

/**
 * 会话表 conversation。
 *
 * <p>时间列统一 BIGINT（Unix 秒），由 {@link #onCreate()} / {@link #onUpdate()} 写入，不用 JPA 审计： 审计默认产出 {@code
 * Instant}/{@code LocalDateTime}，与本项目「全部 Unix 秒 integer」的契约不一致。
 *
 * <p>软删语义：{@code deleted=true} 的行仍然存在，所有查询都带 {@code deleted=false}。
 */
@Entity
@Table(name = "conversation")
public class Conversation {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "title", nullable = false, length = 255)
    private String title;

    @Column(name = "deleted", nullable = false)
    private Boolean deleted;

    @Column(name = "created_at", nullable = false)
    private Long createdAt;

    @Column(name = "updated_at", nullable = false)
    private Long updatedAt;

    public Conversation() {
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
        if (title == null || title.isBlank()) {
            title = "新会话";
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

    public Long getUserId() {
        return userId;
    }

    public void setUserId(Long userId) {
        this.userId = userId;
    }

    public String getTitle() {
        return title;
    }

    public void setTitle(String title) {
        this.title = title;
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
