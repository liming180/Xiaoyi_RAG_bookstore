package com.xiaoyi.rag.model.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** 参数实验；归属列 user_id 由 V7 迁移加入，历史行保持 NULL。 */
@Entity
@Table(name = "experiment")
public class Experiment {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 归属用户；V7 之前的历史行为 NULL，不做回填。 */
    @Column(name = "user_id")
    private Long userId;

    @Column(nullable = false, length = 255)
    private String name;

    @Column(nullable = false, length = 16)
    private String status;

    @Column(nullable = false)
    private Integer progress;

    @Column(name = "total_groups", nullable = false)
    private Integer totalGroups;

    @Column(name = "finished_groups", nullable = false)
    private Integer finishedGroups;

    @Column(name = "axes_json", nullable = false, columnDefinition = "JSON")
    private String axesJson;

    @Column(name = "created_at", nullable = false)
    private Long createdAt;

    @Column(name = "finished_at")
    private Long finishedAt;

    @Column(name = "error", columnDefinition = "TEXT")
    private String error;

    public Long getId() {
        return id;
    }

    public Long getUserId() {
        return userId;
    }

    public void setUserId(Long userId) {
        this.userId = userId;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public Integer getProgress() {
        return progress;
    }

    public void setProgress(Integer progress) {
        this.progress = progress;
    }

    public Integer getTotalGroups() {
        return totalGroups;
    }

    public void setTotalGroups(Integer totalGroups) {
        this.totalGroups = totalGroups;
    }

    public Integer getFinishedGroups() {
        return finishedGroups;
    }

    public void setFinishedGroups(Integer finishedGroups) {
        this.finishedGroups = finishedGroups;
    }

    public String getAxesJson() {
        return axesJson;
    }

    public void setAxesJson(String axesJson) {
        this.axesJson = axesJson;
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

    public String getError() {
        return error;
    }

    public void setError(String error) {
        this.error = error;
    }
}
