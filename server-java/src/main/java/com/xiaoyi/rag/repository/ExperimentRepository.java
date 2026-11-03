package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.Experiment;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ExperimentRepository extends JpaRepository<Experiment, Long> {
    List<Experiment> findByStatusIn(List<String> statuses);
}
