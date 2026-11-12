package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.Document;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

/**
 * 资料仓储。
 *
 * <p>H2 之后所有对外方法都带 {@code userId}（资料归属人 {@code uploaded_by}）：跨用户读不到、改不到、删不到，
 * 同内容去重也只在本人范围内生效。只有内部轮询/统计类查询才允许全局。
 */
@Repository
public interface DocumentRepository extends JpaRepository<Document, Long> {

    List<Document> findByUploadedByAndDeletedFalseOrderByUpdatedAtDescIdDesc(Long userId);

    Optional<Document> findByIdAndUploadedByAndDeletedFalse(Long id, Long userId);

    /** 去重：同一用户、同一份内容（sha256 相同）且未删除的资料。 */
    Optional<Document> findFirstBySha256AndUploadedByAndDeletedFalse(String sha256, Long userId);

    /** 软删：必须同时匹配归属人，否则等于给了越权删除的口子。 */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("update Document d set d.deleted = true where d.id = :id and d.uploadedBy = :userId")
    int softDeleteByIdAndUploadedBy(@Param("id") Long id, @Param("userId") Long userId);

    /** 未删除资料总数（按用户统计）。 */
    long countByUploadedByAndDeletedFalse(Long userId);

    /**
     * 把该用户「已建好索引」的资料统一标脏。
     *
     * <p>库里没有单独的 index_status 列，语料变了，原先 INDEXED 的行就不再可信。只动本人资料。
     *
     * @return 受影响行数
     */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query(
            "update Document d set d.status = 'NEEDS_REBUILD' where d.uploadedBy = :userId and"
                    + " d.deleted = false and d.status = 'INDEXED'")
    int markIndexedAsNeedsRebuild(@Param("userId") Long userId);

    /**
     * 建库成功：把这份资料的片段数落库并置 INDEXED，同时用 revision 做「快照未被改动」的原子判据。
     *
     * <p>条件里带 {@code d.revision = :snapshotRevision}：建库期间用户改了标题/标签/正文，revision 已经变了， 这条 update 就影响
     * 0 行，调用方据此把任务判失败而不是静默覆盖。JPQL 批量 update 不触发 {@code @Version}， 所以这里显式 {@code d.revision =
     * d.revision + 1}。
     *
     * @return 受影响行数（0 表示资料在快照之后被改过或已删除/停用）
     */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query(
            "update Document d set d.status = 'INDEXED', d.chunkCount = :chunkCount,"
                    + " d.errorMsg = null, d.revision = d.revision + 1, d.updatedAt = :now"
                    + " where d.id = :id and d.uploadedBy = :userId and d.deleted = false"
                    + " and d.revision = :snapshotRevision and d.status <> 'DISABLED'")
    int markSnapshotIndexed(
            @Param("userId") Long userId,
            @Param("id") Long id,
            @Param("snapshotRevision") Long snapshotRevision,
            @Param("chunkCount") Integer chunkCount,
            @Param("now") Long now);

    /** 建库失败：只把仍是「待建」状态的本人资料标 FAILED，别覆盖用户刚改过的行。 */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query(
            "update Document d set d.status = 'FAILED', d.errorMsg = :error"
                    + " where d.uploadedBy = :userId and d.deleted = false"
                    + " and d.status in ('UPLOADING', 'PARSING')")
    int markFailedForOwner(@Param("userId") Long userId, @Param("error") String error);

    /** 按状态取未删除资料（判定 /index/status 的 needs_rebuild 用）。 */
    List<Document> findByUploadedByAndDeletedFalseAndStatusIn(
            Long userId, Collection<String> statuses);

    /** 可建库资料：本人的、未删除的、未被用户停用的。 */
    List<Document> findByUploadedByAndDeletedFalseAndStatusNot(Long userId, String status);
}
