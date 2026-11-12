package com.xiaoyi.rag.model.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import java.util.List;

/** 反馈请求，对应 FeedbackRequest。 */
public record FeedbackRequest(
        @NotBlank(message = "rating 不能为空")
                @Pattern(regexp = "up|down", message = "rating 只能是 up / down")
                String rating,
        List<String> tags,
        String comment) {}
