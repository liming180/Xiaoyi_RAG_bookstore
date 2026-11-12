package com.xiaoyi.rag.model.entity;

import jakarta.persistence.*;

@Entity
@Table(name = "experiment_run")
public class ExperimentRun {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "experiment_id", nullable = false)
    private Long experimentId;

    @Column(name = "group_index", nullable = false)
    private Integer groupIndex;

    @Column(name = "params_json", nullable = false, columnDefinition = "JSON")
    private String paramsJson;

    @Column(name = "metrics_json", nullable = false, columnDefinition = "JSON")
    private String metricsJson;

    @Column(name = "elapsed_ms", nullable = false)
    private Long elapsedMs;

    public Long getId() {
        return id;
    }

    public Long getExperimentId() {
        return experimentId;
    }

    public void setExperimentId(Long experimentId) {
        this.experimentId = experimentId;
    }

    public Integer getGroupIndex() {
        return groupIndex;
    }

    public void setGroupIndex(Integer groupIndex) {
        this.groupIndex = groupIndex;
    }

    public String getParamsJson() {
        return paramsJson;
    }

    public void setParamsJson(String paramsJson) {
        this.paramsJson = paramsJson;
    }

    public String getMetricsJson() {
        return metricsJson;
    }

    public void setMetricsJson(String metricsJson) {
        this.metricsJson = metricsJson;
    }

    public Long getElapsedMs() {
        return elapsedMs;
    }

    public void setElapsedMs(Long elapsedMs) {
        this.elapsedMs = elapsedMs;
    }
}
