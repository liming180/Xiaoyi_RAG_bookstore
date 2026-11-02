package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.IndexTask;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

/** 建库任务仓储。 */
@Repository
public interface IndexTaskRepository extends JpaRepository<IndexTask, Long> {

    /** 最近一条任务（不限状态），供 GET /index/status 推导 needs_rebuild。 */
    Optional<IndexTask> findFirstByOrderByCreatedAtDescIdDesc();

    /** 在跑的任务（PENDING / RUNNING）。 */
    List<IndexTask> findByStatusInOrderByCreatedAtDesc(Collection<String> statuses);

    /** 按状态取最近一条。 */
    Optional<IndexTask> findFirstByStatusOrderByCreatedAtDescIdDesc(String status);

    /** 在跑的任务（轮询扫描用），按创建时间升序保证先进先出。 */
    List<IndexTask> findByStatusInOrderByCreatedAtAsc(Collection<String> statuses);

    /** 最近一条成功的任务，供 /index/status 比对参数。 */
    Optional<IndexTask> findFirstByStatusOrderByFinishedAtDescIdDesc(String status);
}
