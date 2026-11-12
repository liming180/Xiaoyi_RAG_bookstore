package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.AuditLog;
import java.util.List;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

/** 操作审计仓储。V11 起由管理端用户管理写入，V12 起支持管理端分页查询。 */
@Repository
public interface AuditLogRepository extends JpaRepository<AuditLog, Long> {

    /** 某个动作的全部记录，按写入顺序。测试用它断言四次操作都落了审计。 */
    List<AuditLog> findByActionOrderByIdAsc(String action);

    /** 针对某个目标对象的记录。 */
    List<AuditLog> findByTargetOrderByIdAsc(String target);

    /**
     * 管理端审计分页查询。
     *
     * <p>三个过滤条件都可为 null（不过滤），全部走参数化条件，不做任何字符串拼接：
     *
     * <ul>
     *   <li>{@code action} 精确匹配动作名（下拉框选，不是自由输入）；
     *   <li>{@code operatorId} 精确匹配操作者；
     *   <li>{@code keyword} 对 target 做包含匹配（例如按 {@code user:7} 查某个账号的全部操作史）。
     * </ul>
     *
     * <p>排序固定 `id desc`（最新在前）：审计日志的价值在「刚刚发生了什么」，倒序是唯一合理的默认。
     */
    @Query(
            "select a from AuditLog a where (:action is null or a.action = :action)"
                    + " and (:operatorId is null or a.userId = :operatorId)"
                    + " and (:keyword is null or a.target like concat('%', :keyword, '%'))"
                    + " order by a.id desc")
    Page<AuditLog> search(
            @Param("action") String action,
            @Param("operatorId") Long operatorId,
            @Param("keyword") String keyword,
            Pageable pageable);
}
