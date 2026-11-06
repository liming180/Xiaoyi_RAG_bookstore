package com.xiaoyi.rag.service;

import com.xiaoyi.rag.model.dto.CreateExperimentRequest;
import com.xiaoyi.rag.model.vo.ExperimentReportVO;
import com.xiaoyi.rag.model.vo.ExperimentVO;

/** 参数实验编排；创建与查询都按归属用户隔离。 */
public interface ExperimentService {

    /**
     * 创建并异步启动一次参数实验。
     *
     * @param userId 归属用户
     * @param request 参数轴与实验名
     * @return 初始实验视图
     */
    ExperimentVO create(Long userId, CreateExperimentRequest request);

    /**
     * 实验进度。
     *
     * @param userId 归属用户；别人的 id 与不存在的 id 一律 40405
     * @param id 实验 id
     * @return 实验视图
     */
    ExperimentVO get(Long userId, String id);

    /**
     * 实验报告。
     *
     * @param userId 归属用户；别人的 id 与不存在的 id 一律 40405
     * @param id 实验 id
     * @return 实验视图与逐组指标
     */
    ExperimentReportVO report(Long userId, String id);

    /** 是否有实验正在执行；这是进程级串行闸门，与用户无关。 */
    boolean isRunning();

    /** 实验进行中拒绝提问；进程级闸门，与用户无关。 */
    void assertChatAvailable();
}
