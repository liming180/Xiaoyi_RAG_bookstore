package com.xiaoyi.rag.service;

import com.xiaoyi.rag.model.dto.CreateExperimentRequest;
import com.xiaoyi.rag.model.vo.ExperimentReportVO;
import com.xiaoyi.rag.model.vo.ExperimentVO;

public interface ExperimentService {
    ExperimentVO create(CreateExperimentRequest request);

    ExperimentVO get(String id);

    ExperimentReportVO report(String id);

    boolean isRunning();

    void assertChatAvailable();
}
