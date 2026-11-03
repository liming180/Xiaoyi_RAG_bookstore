package com.xiaoyi.rag.service;

import com.xiaoyi.rag.model.dto.EvalBatchRequest;
import com.xiaoyi.rag.model.vo.EvalQuestionVO;
import com.xiaoyi.rag.model.vo.EvalRunVO;
import java.util.List;
import java.util.Map;

public interface EvalService {
    List<EvalQuestionVO> questions();

    List<com.xiaoyi.rag.model.vo.EvalCaseResultVO> evaluate(
            List<EvalQuestionVO> questions, int k, Map<String, Object> options);

    EvalRunVO start(EvalBatchRequest request);

    List<EvalRunVO> runs();

    EvalRunVO run(String id);
}
