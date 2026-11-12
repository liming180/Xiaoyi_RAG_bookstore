package com.xiaoyi.rag.model.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

/**
 * badcase 候选处置请求，对应 CandidateDecisionRequest。
 *
 * @param status 目标状态，只能是 accepted / ignored
 * @param keywords 人工补的判分关键词，语法同 {@code assets/eval/keywords.csv}（组内 {@code /} 同义、组间 {@code |}
 *     必须全中）。只有 {@code status=accepted} 时才写入；留空表示「可以进实验但不计分」
 */
public record CandidateDecisionRequest(
        @NotBlank(message = "status 不能为空")
                @Pattern(regexp = "accepted|ignored", message = "status 只能是 accepted / ignored")
                String status,
        @Size(max = 512, message = "keywords 最多 512 字符") String keywords) {

    /** 兼容旧调用：只带状态，不补关键词。 */
    public CandidateDecisionRequest(String status) {
        this(status, null);
    }
}
