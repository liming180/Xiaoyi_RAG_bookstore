package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.EvalCandidate;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

/**
 * 候选池仓储。
 *
 * <p>候选行本身没有 user_id 列（V7 未加，也不打算加）：归属只能沿 {@code candidate.message_id → message.conversation_id →
 * conversation.user_id} 推导。所以这里的每个列表 / 计数 / 存在性查询都写成三表连接， 由 JPQL 直接交给数据库做归属过滤，而不是先全表捞回来再在内存里筛。
 */
@Repository
public interface EvalCandidateRepository extends JpaRepository<EvalCandidate, Long> {

    /** 同一消息只会产生一条候选；调用前已校验消息归属，因此这个判断不需要再带用户。 */
    boolean existsByMessageId(Long messageId);

    /**
     * 当前用户自己的候选池，按创建时间倒序（同秒按 id 倒序，保证顺序稳定）。
     *
     * @param userId 归属用户
     * @return 该用户会话下消息产生的候选
     */
    @Query(
            "select c from EvalCandidate c, Message m, Conversation conv"
                    + " where c.messageId = m.id and m.conversationId = conv.id"
                    + " and conv.userId = :userId"
                    + " order by c.createdAt desc, c.id desc")
    List<EvalCandidate> findOwnedBy(@Param("userId") Long userId);

    /**
     * 当前用户自己某状态的候选数量。
     *
     * @param userId 归属用户
     * @param status 候选状态
     * @return 命中行数
     */
    @Query(
            "select count(c) from EvalCandidate c, Message m, Conversation conv"
                    + " where c.messageId = m.id and m.conversationId = conv.id"
                    + " and conv.userId = :userId and c.status = :status")
    long countOwnedByStatus(@Param("userId") Long userId, @Param("status") String status);

    /**
     * 当前用户自己某状态的候选，按创建时间倒序。
     *
     * @param userId 归属用户
     * @param status 候选状态
     * @return 命中行
     */
    @Query(
            "select c from EvalCandidate c, Message m, Conversation conv"
                    + " where c.messageId = m.id and m.conversationId = conv.id"
                    + " and conv.userId = :userId and c.status = :status"
                    + " order by c.createdAt desc, c.id desc")
    List<EvalCandidate> findOwnedByStatus(
            @Param("userId") Long userId, @Param("status") String status);

    /**
     * 按 id 取当前用户自己某状态的候选；实验选题走这条，别人的 id 与不存在的 id 都返回空。
     *
     * @param id 候选 id
     * @param userId 归属用户
     * @param status 候选状态
     * @return 命中行
     */
    @Query(
            "select c from EvalCandidate c, Message m, Conversation conv"
                    + " where c.id = :id and c.messageId = m.id and m.conversationId = conv.id"
                    + " and conv.userId = :userId and c.status = :status")
    java.util.Optional<EvalCandidate> findOwnedByIdAndStatus(
            @Param("id") Long id, @Param("userId") Long userId, @Param("status") String status);

    /**
     * 候选是否属于该用户；别人的候选与不存在的 id 都返回 false，调用方统一按 40404 处理。
     *
     * @param id 候选 id
     * @param userId 归属用户
     * @return 归属命中为 true
     */
    @Query(
            "select count(c) > 0 from EvalCandidate c, Message m, Conversation conv"
                    + " where c.id = :id and c.messageId = m.id and m.conversationId = conv.id"
                    + " and conv.userId = :userId")
    boolean existsOwnedById(@Param("id") Long id, @Param("userId") Long userId);
}
