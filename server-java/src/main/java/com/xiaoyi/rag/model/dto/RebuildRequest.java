package com.xiaoyi.rag.model.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;

/** 重建索引请求，对应 RebuildRequest。 */
public record RebuildRequest(
        @NotNull(message = "片段长度不能为空")
                @Min(value = 50, message = "片段长度需在 50-1000 之间")
                @Max(value = 1000, message = "片段长度需在 50-1000 之间")
                Integer chunkSize,
        @NotNull(message = "重叠字数不能为空") @Min(value = 0, message = "重叠字数必须小于片段长度") Integer overlap) {}
