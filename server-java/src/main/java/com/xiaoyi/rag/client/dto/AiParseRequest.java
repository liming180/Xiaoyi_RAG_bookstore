package com.xiaoyi.rag.client.dto;

import java.util.List;

/**
 * 触发入库的请求，对应内部契约 {@code InternalParseRequest}。
 *
 * <p>{@code chunkSize} / {@code overlap} 必须如实带给 Python 并落进它的 manifest —— Java 侧 {@code
 * /index/status} 的 needs_rebuild 判定要拿「当前生效参数」和「manifest 里的参数」比对，两边不一致就说明有人改了参数没重建。
 *
 * <p>H3 追加两个字段：
 *
 * <ul>
 *   <li>{@code submissionKey} —— 幂等键。同一个用户用同一个 key 重试（超时、重启、用户连点），Python 侧必须回同一个 task_id，
 *       不能凭空多出一个任务。
 *   <li>{@code generation} —— 代际标识。任务成功时 Java 用它把「当前生效的一代片段」指向这一批，失败的一代不覆盖上一代。
 * </ul>
 */
public record AiParseRequest(
        List<AiParseDocumentItem> documents,
        Integer chunkSize,
        Integer overlap,
        String submissionKey,
        String generation) {}
