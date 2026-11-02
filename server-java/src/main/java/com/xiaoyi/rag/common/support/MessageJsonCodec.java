package com.xiaoyi.rag.common.support;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.xiaoyi.rag.model.vo.CitationVO;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * 消息表 JSON 列的读写编解码。
 *
 * <p>库里 {@code citations_json} / {@code retrieval_trace_json} / {@code usage_json} 是 MySQL JSON
 * 类型，实体按 {@code String} 存原文（见 {@link com.xiaoyi.rag.model.entity.Message}）。出参要转成
 * 契约里的结构化形状，统一收在这里，避免每个 Service 各写一遍。
 *
 * <p>解析失败不抛异常：脏数据不该让整个列表接口 500，降级成空值并留一条 warn 日志。
 */
@Component
public class MessageJsonCodec {

    private static final Logger log = LoggerFactory.getLogger(MessageJsonCodec.class);

    private static final TypeReference<List<CitationVO>> CITATION_LIST = new TypeReference<>() {};

    private static final TypeReference<Map<String, Integer>> USAGE_MAP = new TypeReference<>() {};

    private final ObjectMapper objectMapper;

    public MessageJsonCodec(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    /**
     * 读引用列表。空串 / null / 脏数据都回空列表，保证出参是 {@code []} 而不是 null。
     *
     * @param json 库里的 JSON 原文
     * @return 引用视图列表，永不为 null
     */
    public List<CitationVO> readCitations(String json) {
        if (json == null || json.isBlank()) {
            return List.of();
        }
        try {
            List<CitationVO> parsed = objectMapper.readValue(json, CITATION_LIST);
            return parsed == null ? List.of() : parsed;
        } catch (Exception ex) {
            log.warn("citations_json 解析失败，降级为空列表：{}", ex.getMessage());
            return List.of();
        }
    }

    /**
     * 读检索轨迹。J2 阶段库里恒为空，J3 落库后才有内容。
     *
     * @param json 库里的 JSON 原文
     * @return 轨迹对象，无则 null
     */
    public Object readTrace(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readValue(json, Object.class);
        } catch (Exception ex) {
            log.warn("retrieval_trace_json 解析失败，降级为 null：{}", ex.getMessage());
            return null;
        }
    }

    /**
     * 读 token 用量。
     *
     * @param json 库里的 JSON 原文
     * @return 用量映射，无则 null
     */
    public Map<String, Integer> readUsage(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readValue(json, USAGE_MAP);
        } catch (Exception ex) {
            log.warn("usage_json 解析失败，降级为 null：{}", ex.getMessage());
            return null;
        }
    }

    /**
     * 写 JSON 原文。null 入参回 null（对应库里 JSON NULL）。
     *
     * @param value 任意可序列化对象
     * @return JSON 原文
     */
    public String write(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception ex) {
            log.warn("JSON 序列化失败，落库为 null：{}", ex.getMessage());
            return null;
        }
    }
}
