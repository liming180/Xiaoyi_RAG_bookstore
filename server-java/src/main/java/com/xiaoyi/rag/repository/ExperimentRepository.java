package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.Experiment;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

/** 参数实验仓储；除启动恢复外，所有查询都按归属用户过滤。 */
public interface ExperimentRepository extends JpaRepository<Experiment, Long> {

    /**
     * 按 id + 归属用户取单条；别人的实验与不存在的 id 返回同一个空结果，调用方统一按 40405 处理。
     *
     * @param id 实验 id
     * @param userId 归属用户
     * @return 命中的实验
     */
    Optional<Experiment> findByIdAndUserId(Long id, Long userId);

    /**
     * 当前用户的实验列表，按创建时间倒序（同秒再按 id 倒序）。
     *
     * @param userId 归属用户
     * @return 该用户的实验列表
     */
    List<Experiment> findAllByUserIdOrderByCreatedAtDescIdDesc(Long userId);

    /**
     * 启动时崩溃恢复用：扫描全部用户的非终态实验。
     *
     * <p>与评测一致，这里刻意不做用户过滤——重启时没有请求上下文，残留行必须全部置为 FAILED。
     *
     * @param statuses 非终态集合
     * @return 全部用户的残留实验
     */
    List<Experiment> findByStatusIn(List<String> statuses);
}
