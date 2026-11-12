package com.xiaoyi.rag.service;

import com.xiaoyi.rag.model.dto.EvalBatchRequest;
import com.xiaoyi.rag.model.vo.EvalCaseResultVO;
import com.xiaoyi.rag.model.vo.EvalQuestionVO;
import com.xiaoyi.rag.model.vo.EvalRunVO;
import java.util.List;
import java.util.Map;

/** 评测编排；除题库外，所有读写都按归属用户隔离。 */
public interface EvalService {

    /**
     * 当前用户启用中的题库（P5-08 起题库是用户数据，来自 {@code eval_question} 表）。
     *
     * @param userId 归属用户
     * @return 可参与选题的题目
     */
    List<EvalQuestionVO> questions(Long userId);

    /**
     * 跑一轮对照评测；供实验链路在后台线程里复用。
     *
     * @param userId 归属用户，透传给 AI 侧
     * @param questions 待评测题目
     * @param k 检索 top-k
     * @param options 额外参数
     * @return 逐题结果
     */
    List<EvalCaseResultVO> evaluate(
            Long userId, List<EvalQuestionVO> questions, int k, Map<String, Object> options);

    /**
     * 创建并异步启动一次批量评测。
     *
     * @param userId 归属用户
     * @param request 模式与 top-k
     * @return 初始批次视图
     */
    EvalRunVO start(Long userId, EvalBatchRequest request);

    /**
     * 当前用户的评测批次列表。
     *
     * @param userId 归属用户
     * @return 批次列表，按创建时间倒序
     */
    List<EvalRunVO> runs(Long userId);

    /**
     * 单次评测详情。
     *
     * @param userId 归属用户；别人的 id 与不存在的 id 一律 40403
     * @param id 批次 id
     * @return 批次详情
     */
    EvalRunVO run(Long userId, String id);
}
