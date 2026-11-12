package com.xiaoyi.rag.common.support;

import com.xiaoyi.rag.client.dto.AiCitation;
import com.xiaoyi.rag.model.vo.CitationVO;
import java.util.ArrayList;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * 内部引用形状 → 对外引用形状的转换（snake_case 语义 → camelCase 契约）。
 *
 * <p>手册 §7 第 2 条要求「逐条原样透传」，但「原样」指的是**语义与取值**，字段名必须按对外契约改写： {@code excerpt → text}、{@code
 * score_stage → stage}、{@code doc_title → docTitle}、{@code heading_path → headingPath}、{@code
 * chunk_id → chunkId}、{@code doc_id → docId}。对照表见 docs/api/openapi-internal.yaml 的
 * info.description。
 *
 * <p>防御策略：Python 少给字段时补默认值而不是抛错，因为一条引用缺 {@code verified} 不该让整轮问答失败。 但 {@code chunkId} / {@code
 * text} 是契约 required 且 {@code text} 有 minLength 1，缺失的引用直接丢弃并 warn —— 留一条空正文的引用会让前端引用卡渲染成空白，比不显示更糟。
 */
@Component
public class CitationMapper {

    private static final Logger log = LoggerFactory.getLogger(CitationMapper.class);

    private static final String DEFAULT_KIND = "chunk";

    /**
     * 批量转换，丢弃不可用的引用。
     *
     * @param source 内部引用列表，可为 null
     * @return 对外引用列表，永不为 null
     */
    public List<CitationVO> toVOs(List<AiCitation> source) {
        if (source == null || source.isEmpty()) {
            return List.of();
        }
        List<CitationVO> result = new ArrayList<>(source.size());
        for (int i = 0; i < source.size(); i++) {
            CitationVO vo = toVO(source.get(i), i);
            if (vo != null) {
                result.add(vo);
            }
        }
        return result;
    }

    /**
     * 单条转换。
     *
     * @param source 内部引用
     * @param index 在列表中的下标，用于给缺失的 ref 补序号
     * @return 对外引用；{@code chunkId} 或正文为空时返回 null
     */
    public CitationVO toVO(AiCitation source, int index) {
        if (source == null) {
            return null;
        }
        String chunkId = trimToNull(source.chunkId());
        String text = trimToNull(source.excerpt());
        if (chunkId == null || text == null) {
            log.warn("丢弃一条缺 chunkId 或正文的引用：chunkId={} index={}", source.chunkId(), index);
            return null;
        }
        return new CitationVO(
                source.ref() == null ? index + 1 : source.ref(),
                chunkId,
                source.docId() == null ? "" : source.docId(),
                source.docTitle() == null ? "" : source.docTitle(),
                source.headingPath() == null ? "" : source.headingPath(),
                text,
                source.start() == null ? 0 : source.start(),
                source.end() == null ? 0 : source.end(),
                source.score() == null ? 0.0d : source.score(),
                trimToNull(source.scoreStage()),
                source.kind() == null ? DEFAULT_KIND : source.kind(),
                source.verified() == null || source.verified());
    }

    /**
     * 去空白并判空。返回的是 **trim 后**的值：{@code chunkId} 有 {@code ^D\d{2}-C\d{3}$} 的模式约束，
     * 带空格会被契约校验打掉；正文首尾空白也只是噪音。
     *
     * @param value 原始值
     * @return trim 后的非空值，或 null
     */
    private String trimToNull(String value) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }
}
