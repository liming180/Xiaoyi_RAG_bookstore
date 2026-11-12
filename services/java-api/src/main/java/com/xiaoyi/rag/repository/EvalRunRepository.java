package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.EvalRun;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

/** 评测批次仓储；除启动恢复外，所有查询都按归属用户过滤。 */
public interface EvalRunRepository extends JpaRepository<EvalRun, Long> {

    /**
     * 当前用户的评测批次，按创建时间倒序（同秒再按 id 倒序，保证分页稳定）。
     *
     * @param userId 归属用户
     * @return 该用户的批次列表
     */
    List<EvalRun> findAllByUserIdOrderByCreatedAtDescIdDesc(Long userId);

    /**
     * 按 id + 归属用户取单条；别人的批次与不存在的 id 返回同一个空结果，调用方统一按 40403 处理。
     *
     * @param id 批次 id
     * @param userId 归属用户
     * @return 命中的批次
     */
    Optional<EvalRun> findByIdAndUserId(Long id, Long userId);

    /**
     * 启动时崩溃恢复用：扫描全部用户的非终态批次。
     *
     * <p>这里刻意不做用户过滤——服务重启时没有任何请求上下文，残留的 PENDING/RUNNING 行属于哪个用户都必须被置为 FAILED， 否则会永远挂在进度条上。
     *
     * @param statuses 非终态集合
     * @return 全部用户的残留批次
     */
    List<EvalRun> findByStatusIn(List<String> statuses);
}
