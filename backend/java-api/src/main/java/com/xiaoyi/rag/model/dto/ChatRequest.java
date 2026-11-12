package com.xiaoyi.rag.model.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;

/** 流式问答请求，对应 ChatRequest。 */
public record ChatRequest(
        String conversationId,
        @NotBlank(message = "问题不能为空") String question,
        @Pattern(regexp = "rag|direct|both", message = "mode 只能是 rag / direct / both") String mode,
        @Min(value = 1, message = "k 不能小于 1") @Max(value = 10, message = "k 不能大于 10") Integer k) {}
