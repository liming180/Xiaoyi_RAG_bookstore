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
 * 用户表 user。
 *
 * <p>J1 阶段的 {@code AuthInterceptor} 把 userId 固定成 1，J2 用它做「会话归属」判定的载体； 真正的登录与口令校验在 J3 之后（当前 {@code
 * login} 仍回 50101）。
 */
@Entity
@Table(name = "user")
public class User {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "username", nullable = false, length = 64)
    private String username;

    /** 显示名。NULL 时前端回退显示 username（V11 新增）。 */
    @Column(name = "display_name", length = 64)
    private String displayName;

    @Column(name = "password_hash", nullable = false, length = 128)
    private String passwordHash;

    @Column(name = "role", nullable = false, length = 32)
    private String role;

    /** 软删标记（V11 新增）。软删后不能登录，也不能再被管理端操作。 */
    @Column(name = "deleted", nullable = false)
    private Boolean deleted;

    @Column(name = "created_at", nullable = false)
    private Long createdAt;

    public User() {
        // JPA 需要无参构造
    }

    @PrePersist
    void onCreate() {
        if (createdAt == null) {
            createdAt = Instant.now().getEpochSecond();
        }
        if (role == null || role.isBlank()) {
            role = "USER";
        }
        if (deleted == null) {
            deleted = Boolean.FALSE;
        }
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    public String getDisplayName() {
        return displayName;
    }

    public void setDisplayName(String displayName) {
        this.displayName = displayName;
    }

    public String getPasswordHash() {
        return passwordHash;
    }

    public void setPasswordHash(String passwordHash) {
        this.passwordHash = passwordHash;
    }

    public String getRole() {
        return role;
    }

    public void setRole(String role) {
        this.role = role;
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
