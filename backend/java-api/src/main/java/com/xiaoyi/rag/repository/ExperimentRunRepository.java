package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.ExperimentRun;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ExperimentRunRepository extends JpaRepository<ExperimentRun, Long> {
    List<ExperimentRun> findByExperimentIdOrderByGroupIndexAsc(Long experimentId);
}
