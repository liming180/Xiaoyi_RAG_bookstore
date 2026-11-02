package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.Document;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

/** 资料仓储。 */
@Repository
public interface DocumentRepository extends JpaRepository<Document, Long> {

    List<Document> findByDeletedFalseOrderByUpdatedAtDescIdDesc();

    Optional<Document> findByIdAndDeletedFalse(Long id);

    /** 去重：同一份内容（sha256 相同）且未删除的资料。 */
    Optional<Document> findFirstBySha256AndDeletedFalse(String sha256);

    /** 软删。 */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("update Document d set d.deleted = true where d.id = :id")
    int softDeleteById(@Param("id") Long id);

    /** 未删除资料总数（index manifest 的 docCount）。 */
    long countByDeletedFalse();

    /**
     * 把当前「已建好索引」的资料统一标脏。
     *
     * <p>手册 §6 第 5 条：任何文档增删改都要把 index_status 置 needs_rebuild。库里没有单独的 index_status 列，故直接从 document
     * 状态推导 —— 语料变了，原先 INDEXED 的行就不再可信。
     *
     * @return 受影响行数
     */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query(
            "update Document d set d.status = 'NEEDS_REBUILD'"
                    + " where d.deleted = false and d.status = 'INDEXED'")
    int markIndexedAsNeedsRebuild();
}
