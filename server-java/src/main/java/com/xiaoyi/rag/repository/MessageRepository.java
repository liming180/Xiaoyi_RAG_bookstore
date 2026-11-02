package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.Message;
import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

/** 消息仓储。 */
@Repository
public interface MessageRepository extends JpaRepository<Message, Long> {

    /** 首页：按 created_at 升序取前 limit 条。 */
    List<Message> findByConversationIdAndDeletedFalseOrderByCreatedAtAscIdAsc(
            Long conversationId, Pageable pageable);

    /** 分页：created_at < before 的更早消息，升序取前 limit 条。 */
    List<Message> findByConversationIdAndDeletedFalseAndCreatedAtLessThanOrderByCreatedAtAscIdAsc(
            Long conversationId, Long before, Pageable pageable);

    /**
     * 取最近若干条消息（倒序），用于拼问答历史。
     *
     * <p>必须倒序取再在内存里反转：直接升序 + {@code PageRequest} 会拿到**最早**的几条， 那正是「最近 5 轮」的反面。
     */
    List<Message> findByConversationIdAndDeletedFalseOrderByCreatedAtDescIdDesc(
            Long conversationId, Pageable pageable);

    Optional<Message> findByIdAndDeletedFalse(Long id);

    /** 会话内消息总数（未删除）。 */
    long countByConversationIdAndDeletedFalse(Long conversationId);

    /** F10 清空：把会话下所有未删除消息置 deleted=true。 */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query(
            "update Message m set m.deleted = true where m.conversationId = :cid and m.deleted ="
                    + " false")
    int softDeleteByConversationId(@Param("cid") Long conversationId);
}
