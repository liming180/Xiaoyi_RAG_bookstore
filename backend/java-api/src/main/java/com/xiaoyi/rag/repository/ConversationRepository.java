package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.Conversation;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

/** 会话仓储。所有查询都带 {@code deleted = false}，软删行对上层不可见。 */
@Repository
public interface ConversationRepository extends JpaRepository<Conversation, Long> {

    /** 会话列表：按 updated_at 倒序（契约 listConversations）。 */
    List<Conversation> findByUserIdAndDeletedFalseOrderByUpdatedAtDesc(Long userId);

    Optional<Conversation> findByIdAndDeletedFalse(Long id);

    /** 统计会话下未删除消息数，供 ConversationVO.messageCount。 */
    @Query("select count(m) from Message m where m.conversationId = :id and m.deleted = false")
    long countAliveMessages(@Param("id") Long id);

    /** 软删会话。 */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("update Conversation c set c.deleted = true where c.id = :id")
    int softDeleteById(@Param("id") Long id);

    /** 新建会话后刷新 updated_at，让它排到列表最前。 */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("update Conversation c set c.updatedAt = :ts where c.id = :id")
    int touch(@Param("id") Long id, @Param("ts") long ts);
}
