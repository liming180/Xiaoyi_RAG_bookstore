package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.EvalCandidate;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface EvalCandidateRepository extends JpaRepository<EvalCandidate, Long> {
    boolean existsByMessageId(Long messageId);

    List<EvalCandidate> findAllByOrderByCreatedAtDescIdDesc();

    long countByStatus(String status);
}
