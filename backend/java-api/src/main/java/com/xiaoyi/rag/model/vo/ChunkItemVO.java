package com.xiaoyi.rag.model.vo;

/**
 * 片段视图，对应契约 {@code components.schemas.ChunkItem}。
 *
 * <p>契约 required 10 项：{@code [chunkId, docId, docTitle, headingPath, text, start, end, kind,
 * verified, index]}，{@code additionalProperties: false}。注意**没有 score** —— 片段浏览是纯列表，不涉及相似度； 带 score
 * 会让契约校验失败（{@code additionalProperties: false}）。
 *
 * @param chunkId 片段号，形如 D02-C001
 * @param docId 所属资料 id
 * @param docTitle 资料标题
 * @param headingPath 标题路径
 * @param text 片段正文
 * @param start 正文起始偏移
 * @param end 正文结束偏移
 * @param kind chunk / summary / rule
 * @param verified 资料是否已核实
 * @param index 全局序号，从 0 开始
 */
public record ChunkItemVO(
        String chunkId,
        String docId,
        String docTitle,
        String headingPath,
        String text,
        Integer start,
        Integer end,
        String kind,
        Boolean verified,
        Integer index) {}
