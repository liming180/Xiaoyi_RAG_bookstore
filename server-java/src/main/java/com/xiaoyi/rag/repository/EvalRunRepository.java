package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.EvalRun;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface EvalRunRepository extends JpaRepository<EvalRun, Long> {
    List<EvalRun> findAllByOrderByCreatedAtDescIdDesc();

    List<EvalRun> findByStatusIn(List<String> statuses);
}
