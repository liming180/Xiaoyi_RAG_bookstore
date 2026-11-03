package com.xiaoyi.rag.model.entity;

import jakarta.persistence.*;

@Entity
@Table(name = "eval_run")
public class EvalRun {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String name;
    private String mode;

    @Column(name = "top_k")
    private Integer topK;

    @Column(name = "question_count")
    private Integer questionCount;

    @Lob
    @Column(name = "result_csv")
    private String resultCsv;

    @Column(name = "summary_json", columnDefinition = "JSON")
    private String summaryJson;

    private String status;
    private Integer progress;

    @Column(name = "created_at")
    private Long createdAt;

    @Column(name = "finished_at")
    private Long finishedAt;

    public Long getId() {
        return id;
    }

    public void setId(Long v) {
        id = v;
    }

    public String getName() {
        return name;
    }

    public void setName(String v) {
        name = v;
    }

    public String getMode() {
        return mode;
    }

    public void setMode(String v) {
        mode = v;
    }

    public Integer getTopK() {
        return topK;
    }

    public void setTopK(Integer v) {
        topK = v;
    }

    public Integer getQuestionCount() {
        return questionCount;
    }

    public void setQuestionCount(Integer v) {
        questionCount = v;
    }

    public String getResultCsv() {
        return resultCsv;
    }

    public void setResultCsv(String v) {
        resultCsv = v;
    }

    public String getSummaryJson() {
        return summaryJson;
    }

    public void setSummaryJson(String v) {
        summaryJson = v;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String v) {
        status = v;
    }

    public Integer getProgress() {
        return progress;
    }

    public void setProgress(Integer v) {
        progress = v;
    }

    public Long getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Long v) {
        createdAt = v;
    }

    public Long getFinishedAt() {
        return finishedAt;
    }

    public void setFinishedAt(Long v) {
        finishedAt = v;
    }
}
