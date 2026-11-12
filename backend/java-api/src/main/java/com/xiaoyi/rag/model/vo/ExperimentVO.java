package com.xiaoyi.rag.model.vo;

public record ExperimentVO(
        String id,
        String name,
        String status,
        int progress,
        int totalGroups,
        int finishedGroups,
        long createdAt,
        Long finishedAt,
        String error) {}
