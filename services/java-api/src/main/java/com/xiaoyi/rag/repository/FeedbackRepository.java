package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.Feedback;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface FeedbackRepository extends JpaRepository<Feedback, Long> {
    Optional<Feedback> findByMessageId(Long messageId);

    long countByRating(String rating);
}
