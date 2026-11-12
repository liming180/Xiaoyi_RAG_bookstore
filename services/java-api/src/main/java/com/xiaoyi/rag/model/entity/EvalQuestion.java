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
 * 评测题库行（P5-08）。
 *
 * <p>旧实现把 13 道题写死在 classpath 的 CSV 并按「必须 13 题」硬校验，资料一多就无题可测。 这张表把它升级成用户可管理的
 * 数据：每个用户拥有自己的一份，可新增、编辑、停用、导入导出。
 *
 * <p>{@code code} 是稳定的人类可读编号（T01 / U001），会被写进评测快照与导出 CSV； {@code id} 只在内部用。分开的理由见 V10 迁移脚本的注释。
 */
@Entity
@Table(name = "eval_question")
public class EvalQuestion {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "code", nullable = false, length = 64)
    private String code;

    /** single 单份资料可答 / cross 需综合多篇 / out 库外题（考察拒答）。 */
    @Column(name = "type", nullable = false, length = 16)
    private String type;

    @Column(name = "question", nullable = false, columnDefinition = "TEXT")
    private String question;

    /**
     * 判分关键词，语法同 {@code assets/eval/keywords.csv}：组内 {@code /} 为同义、组间 {@code |} 必须全中。
     *
     * <p>空串是合法的 —— 允许「先建题后补关键词」，judge() 对空关键词一律判 true（不参与通过率分母）。 这与候选池「没补关键词 也能进实验，只是不计分」的口径一致。
     */
    @Column(name = "keywords", nullable = false, length = 512)
    private String keywords;

    @Column(name = "evidence", length = 512)
    private String evidence;

    /** seed 内置种子 / manual 手工新增 / generated 自动生成 / import CSV 导入。 */
    @Column(name = "source", nullable = false, length = 16)
    private String source;

    /**
     * 1 = 参与选题，0 = 停用。
     *
     * <p>停用而不是删除：历史评测的 {@code summary_json} 里存着题号快照，硬删会让历史详情点开只剩孤儿 id。
     */
    @Column(name = "enabled", nullable = false)
    private Boolean enabled = Boolean.TRUE;

    @Column(name = "created_at", nullable = false)
    private Long createdAt;

    @Column(name = "updated_at")
    private Long updatedAt;

    @PrePersist
    void onCreate() {
        long now = Instant.now().getEpochSecond();
        if (createdAt == null) {
            createdAt = now;
        }
        updatedAt = now;
    }

    @PreUpdate
    void onUpdate() {
        updatedAt = Instant.now().getEpochSecond();
    }

    public Long getId() {
        return id;
    }

    public Long getUserId() {
        return userId;
    }

    public void setUserId(Long userId) {
        this.userId = userId;
    }

    public String getCode() {
        return code;
    }

    public void setCode(String code) {
        this.code = code;
    }

    public String getType() {
        return type;
    }

    public void setType(String type) {
        this.type = type;
    }

    public String getQuestion() {
        return question;
    }

    public void setQuestion(String question) {
        this.question = question;
    }

    public String getKeywords() {
        return keywords;
    }

    public void setKeywords(String keywords) {
        this.keywords = keywords;
    }

    public String getEvidence() {
        return evidence;
    }

    public void setEvidence(String evidence) {
        this.evidence = evidence;
    }

    public String getSource() {
        return source;
    }

    public void setSource(String source) {
        this.source = source;
    }

    public Boolean getEnabled() {
        return enabled;
    }

    public void setEnabled(Boolean enabled) {
        this.enabled = enabled;
    }

    public Long getCreatedAt() {
        return createdAt;
    }

    public Long getUpdatedAt() {
        return updatedAt;
    }
}
