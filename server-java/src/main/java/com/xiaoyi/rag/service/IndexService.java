package com.xiaoyi.rag.service;

import com.xiaoyi.rag.model.dto.RebuildRequest;
import com.xiaoyi.rag.model.vo.ChunkItemVO;
import com.xiaoyi.rag.model.vo.IndexStatusVO;
import com.xiaoyi.rag.model.vo.IndexTaskVO;
import java.util.List;

/**
 * 建库编排：状态查询、触发重建、任务轮询、片段浏览。
 *
 * <p>四个能力对应手册 §J4 的四条接口；{@link #pollOnce()} 没有对外路由，只被 {@code IndexTaskPoller} 的定时任务调用。
 *
 * <p>H2 起除 {@link #pollOnce()} 外全部方法都以 {@code userId} 为首参：资料、任务、片段都是用户私有资产， 任何一条查询漏掉归属人都会让 A 看到 B
 * 的知识库。
 */
public interface IndexService {

    /**
     * 索引状态。
     *
     * <p>注意 {@code status=unavailable} 是**成功响应**（HTTP 200），不是 503 —— 契约里这条路由的 {@code x-error-codes}
     * 只有 40100/50000。Python 不可达属于「知识库暂时不可用」这一业务状态， 前端要能正常渲染降级文案。
     *
     * @param userId 当前用户
     * @return 状态视图
     */
    IndexStatusVO status(Long userId);

    /**
     * 触发重建，返回刚建的任务。
     *
     * @param userId 当前用户
     * @param request 片段长度与重叠字数
     * @return 任务视图（status=PENDING，stage=parsing）
     */
    IndexTaskVO rebuild(Long userId, RebuildRequest request);

    /**
     * 查单个任务，供前端 1s 轮询。
     *
     * @param userId 当前用户
     * @param id 任务 id（对外契约的 EntityId）
     * @return 任务视图
     */
    IndexTaskVO task(Long userId, String id);

    /**
     * 片段列表，三路过滤可任意组合。
     *
     * @param userId 当前用户
     * @param docId 资料 id，空表示不过滤
     * @param q 正文关键词，大小写敏感子串匹配，空表示不过滤
     * @param kind chunk / summary / rule，空表示不过滤
     * @return 片段列表
     */
    List<ChunkItemVO> listChunks(Long userId, String docId, String q, String kind);

    /** 推进所有非终态任务一格。由定时任务调用，不对外暴露，因此是全库扫描。 */
    void pollOnce();
}
