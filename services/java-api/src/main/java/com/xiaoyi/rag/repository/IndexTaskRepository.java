package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.IndexTask;
import jakarta.persistence.LockModeType;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

/** Owner-scoped index tasks. Global scanning is reserved for the internal poller. */
@Repository
public interface IndexTaskRepository extends JpaRepository<IndexTask, Long> {
    Optional<IndexTask> findByIdAndUserId(Long id, Long userId);

    Optional<IndexTask> findFirstByUserIdAndStatusOrderByFinishedAtDescIdDesc(
            Long userId, String status);

    List<IndexTask> findByUserIdAndStatusInOrderByCreatedAtDesc(
            Long userId, Collection<String> statuses);

    List<IndexTask> findByStatusInOrderByCreatedAtAsc(Collection<String> statuses);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select t from IndexTask t where t.id=:id and t.userId=:userId")
    Optional<IndexTask> lockOwned(@Param("userId") Long userId, @Param("id") Long id);
}
