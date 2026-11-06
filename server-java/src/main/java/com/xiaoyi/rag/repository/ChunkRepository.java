package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.Chunk;
import java.util.Collection;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

/**
 * 片段缓存仓储。
 *
 * <p>过滤全部在内存里做：片段总量是「几十份资料 × 每份几十段」的量级，一次全表读出来再按 {@code q} 做子串匹配， 比拼动态 SQL 简单且行为确定（{@code q}
 * 要求大小写敏感的子串匹配，SQL 里还要考虑排序规则）。真到需要分页的量级再换实现。
 *
 * <p>H2 起所有查询都必须带 {@code userId}：片段缓存是「以最后一次成功建库为准」的整代替换， 一旦按全局删除，A 重建就会把 B 的片段一起清掉。
 */
@Repository
public interface ChunkRepository extends JpaRepository<Chunk, Long> {

    /** 某用户的片段，按全局序号升序，保证列表顺序稳定。 */
    List<Chunk> findByUserIdOrderBySeqAscIdAsc(Long userId);

    long countByUserId(Long userId);

    long countByTaskId(Long taskId);

    /** 建库成功时整代替换：先清掉该用户上一次的产物。 */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("delete from Chunk c where c.userId = :userId and c.taskId <> :taskId")
    int deleteByUserIdAndTaskIdNot(@Param("userId") Long userId, @Param("taskId") Long taskId);

    /** 按资料 id 批量查（供文档删除时清理）。 */
    List<Chunk> findByDocIdIn(Collection<Long> docIds);
}
