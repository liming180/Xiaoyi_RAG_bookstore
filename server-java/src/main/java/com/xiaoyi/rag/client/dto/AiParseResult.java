package com.xiaoyi.rag.client.dto;

/**
 * 入库触发结果，对应内部契约 {@code ParseAccepted}。
 *
 * <p>{@code taskId} 是 Python 侧的任务标识，Java 必须存进 {@code index_task.external_task_id}， 后续轮询靠它定位；它和 Java
 * 自己的 {@code index_task.id}（对外契约的 taskId）是两个东西。
 */
public record AiParseResult(String taskId, Integer docCount) {}
