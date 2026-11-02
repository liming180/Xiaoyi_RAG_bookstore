package com.xiaoyi.rag.model.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;

/** badcase 候选处置请求，对应 CandidateDecisionRequest。 */
public record CandidateDecisionRequest(
        @NotBlank(message = "status 不能为空")
                @Pattern(regexp = "accepted|ignored", message = "status 只能是 accepted / ignored")
                String status) {}
