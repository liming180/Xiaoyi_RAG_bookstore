package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.EvalQuestion;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

/** 评测题库仓储（P5-08）：所有查询都按 {@code user_id} 过滤，别人的题号一律当作「不存在」。 */
@Repository
public interface EvalQuestionRepository extends JpaRepository<EvalQuestion, Long> {

    /**
     * 当前用户的全部题目（含停用），按题型 → 题号排序。
     *
     * <p>题型固定 single → cross → out 的顺序，与前端分组展示一致，避免每次在内存里再排一遍。
     *
     * @param userId 归属用户
     * @return 该用户的题库
     */
    @Query(
            "select q from EvalQuestion q where q.userId = :userId"
                    + " order by case q.type when 'single' then 0 when 'cross' then 1 else 2 end,"
                    + " q.code asc, q.id asc")
    List<EvalQuestion> findAllOwnedBy(@Param("userId") Long userId);

    /**
     * 当前用户**启用中**的题目，选题与批量评测走这条。
     *
     * @param userId 归属用户
     * @return 可参与选题的题目
     */
    @Query(
            "select q from EvalQuestion q where q.userId = :userId and q.enabled = true"
                    + " order by case q.type when 'single' then 0 when 'cross' then 1 else 2 end,"
                    + " q.code asc, q.id asc")
    List<EvalQuestion> findEnabledOwnedBy(@Param("userId") Long userId);

    /** 当前用户是否已有题库（首次进评测页时用它决定要不要灌种子）。 */
    long countByUserId(Long userId);

    /** 同一用户下题号唯一；新增前用它拦重复。 */
    boolean existsByUserIdAndCode(Long userId, String code);

    /** 按题号取当前用户的题；别人的 code 等同不存在。 */
    Optional<EvalQuestion> findByUserIdAndCode(Long userId, String code);

    /** 按主键取当前用户的题；别人的 id 等同不存在。 */
    Optional<EvalQuestion> findByIdAndUserId(Long id, Long userId);

    /** 当前用户启用中的某题型题数，用于前端题型开关上显示「N 道」。 */
    @Query(
            "select count(q) from EvalQuestion q where q.userId = :userId and q.enabled = true"
                    + " and q.type = :type")
    long countEnabledOwnedByType(@Param("userId") Long userId, @Param("type") String type);
}
