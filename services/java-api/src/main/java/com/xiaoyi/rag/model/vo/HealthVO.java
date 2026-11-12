package com.xiaoyi.rag.model.vo;

/**
 * 健康检查返回体，对应 {@code GET /api/v1/health} 的 data。
 *
 * <p>VO 而非 Map，是为了让 springdoc 能生成稳定的 schema。
 */
public record HealthVO(String status) {

    public static HealthVO up() {
        return new HealthVO("UP");
    }
}
