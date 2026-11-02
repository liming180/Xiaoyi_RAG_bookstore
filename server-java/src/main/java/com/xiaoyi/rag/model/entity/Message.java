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
 * 消息表 message。
 *
 * <p>JSON 列（citations / trace / usage）在库里是 MySQL JSON 类型，这里按 {@code String} 存原文： J2
 * 阶段只做读写透传，不做结构化查询，省掉一层 TypeHandler。
 *
 * <p>不用 {@code @Lob}：Hibernate 6 对 {@code @Lob} + MySQL 会走 LOB 流式读取， 与 {@code columnDefinition}
 * 组合容易踩驱动坑；直接用 {@code columnDefinition} 声明真实类型更稳。
 *
 * <p>软删语义：F10 清空会话消息与删除会话都只置 {@code deleted=true}，不物理删行。
 */
@Entity
@Table(name = "message")
public class Message {

    public static final String ROLE_USER = "user";
    public static final String ROLE_ASSISTANT = "assistant";

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "conversation_id", nullable = false)
    private Long conversationId;

    @Column(name = "role", nullable = false, length = 16)
    private String role;

    @Column(name = "content", nullable = false, columnDefinition = "MEDIUMTEXT")
    private String content;

    @Column(name = "mode", length = 16)
    private String mode;

    @Column(name = "top_k")
    private Integer topK;

    @Column(name = "citations_json", columnDefinition = "JSON")
    private String citationsJson;

    @Column(name = "retrieval_trace_json", columnDefinition = "JSON")
    private String retrievalTraceJson;

    @Column(name = "usage_json", columnDefinition = "JSON")
    private String usageJson;

    @Column(name = "elapsed_ms")
    private Long elapsedMs;

    @Column(name = "degraded", nullable = false)
    private Boolean degraded;

    @Column(name = "feedback", length = 8)
    private String feedback;

    @Column(name = "deleted", nullable = false)
    private Boolean deleted;

    @Column(name = "created_at", nullable = false)
    private Long createdAt;

    public Message() {
        // JPA 需要无参构造
    }

    @PrePersist
    void onCreate() {
        if (createdAt == null) {
            createdAt = Instant.now().getEpochSecond();
        }
        if (deleted == null) {
            deleted = false;
        }
        if (degraded == null) {
            degraded = false;
        }
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public Long getConversationId() {
        return conversationId;
    }

    public void setConversationId(Long conversationId) {
        this.conversationId = conversationId;
    }

    public String getRole() {
        return role;
    }

    public void setRole(String role) {
        this.role = role;
    }

    public String getContent() {
        return content;
    }

    public void setContent(String content) {
        this.content = content;
    }

    public String getMode() {
        return mode;
    }

    public void setMode(String mode) {
        this.mode = mode;
    }

    public Integer getTopK() {
        return topK;
    }

    public void setTopK(Integer topK) {
        this.topK = topK;
    }

    public String getCitationsJson() {
        return citationsJson;
    }

    public void setCitationsJson(String citationsJson) {
        this.citationsJson = citationsJson;
    }

    public String getRetrievalTraceJson() {
        return retrievalTraceJson;
    }

    public void setRetrievalTraceJson(String retrievalTraceJson) {
        this.retrievalTraceJson = retrievalTraceJson;
    }

    public String getUsageJson() {
        return usageJson;
    }

    public void setUsageJson(String usageJson) {
        this.usageJson = usageJson;
    }

    public Long getElapsedMs() {
        return elapsedMs;
    }

    public void setElapsedMs(Long elapsedMs) {
        this.elapsedMs = elapsedMs;
    }

    public Boolean getDegraded() {
        return degraded;
    }

    public void setDegraded(Boolean degraded) {
        this.degraded = degraded;
    }

    public String getFeedback() {
        return feedback;
    }

    public void setFeedback(String feedback) {
        this.feedback = feedback;
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
}
