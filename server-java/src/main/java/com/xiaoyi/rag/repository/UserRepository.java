package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.User;
import java.util.Optional;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

/**
 * 用户仓储。
 *
 * <p>V11 之后多了一条硬约束：<b>已软删的行在业务查询里等同不存在</b>。所以除管理端排障用的 {@link #findAnyByUsername} / {@link
 * #findByIdIncludingDeleted} 之外，所有查询都带 {@code deleted = false}。
 *
 * <p>为什么登录要用 {@code findByUsernameAndDeletedFalse} 而不是查出后再判：软删语义必须在 SQL 层生效，
 * 否则任何漏判一处的地方都会变成「删了还能登」。
 */
@Repository
public interface UserRepository extends JpaRepository<User, Long> {

    /** 可登录的账号（软删行查不到）。登录链路用这条。 */
    Optional<User> findByUsernameAndDeletedFalse(String username);

    /** 任一状态的账号，含软删。仅用于创建时判重名（重名要连软删行一起挡）。 */
    @Query("select u from User u where u.username = :username")
    Optional<User> findAnyByUsername(@Param("username") String username);

    /** 含软删按主键取。仅用于管理端排障路径（方法名不能交给派生查询解析，必须显式写 JPQL）。 */
    @Query("select u from User u where u.id = :id")
    Optional<User> findByIdIncludingDeleted(@Param("id") Long id);

    /** 未软删 + 指定角色。鉴权拦截器用它确认 ADMIN 身份。 */
    Optional<User> findByIdAndDeletedFalse(Long id);

    long countByDeletedFalse();

    /** 用户名是否已被占用（含软删行：软删行的 username 仍然占着唯一键）。 */
    boolean existsByUsername(String username);

    /**
     * 管理端分页列表。
     *
     * <p>默认只回未软删的行；{@code keyword} 非空时对 username 前缀 + displayName 包含做匹配（两列都用参数化 LIKE， 不接受任何拼接）。
     */
    @Query(
            "select u from User u where (:includeDeleted = true or u.deleted = false)"
                    + " and (:keyword is null or u.username like concat(:keyword, '%')"
                    + " or u.displayName like concat('%', :keyword, '%'))"
                    + " order by u.createdAt asc, u.id asc")
    Page<User> search(
            @Param("keyword") String keyword,
            @Param("includeDeleted") boolean includeDeleted,
            Pageable pageable);
}
