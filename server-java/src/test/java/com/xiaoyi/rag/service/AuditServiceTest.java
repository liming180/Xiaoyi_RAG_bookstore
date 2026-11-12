package com.xiaoyi.rag.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.xiaoyi.rag.model.entity.AuditLog;
import com.xiaoyi.rag.model.entity.User;
import com.xiaoyi.rag.model.vo.AdminAuditPageVO;
import com.xiaoyi.rag.repository.AuditLogRepository;
import com.xiaoyi.rag.repository.UserRepository;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.Pageable;

/**
 * 审计查询（只读）的分页、过滤与「操作者名解析」。
 *
 * <p>这里钉三件事：
 *
 * <ol>
 *   <li>过滤参数为空时**不能**被当成「匹配空字符串」——否则一进页面就是空列表；
 *   <li>操作者用户名一次批量解析（不是逐行查），且查不到时给 null 而不是 500；
 *   <li>分页参数被夹到合法区间，不把 9999 这种值透传给数据库。
 * </ol>
 */
class AuditServiceTest {

    private final AuditLogRepository audits = mock(AuditLogRepository.class);
    private final UserRepository users = mock(UserRepository.class);
    private final AuditService service = new AuditService(audits, users);

    @BeforeEach
    void defaults() {
        when(audits.search(any(), any(), any(), any(Pageable.class)))
                .thenReturn(new PageImpl<>(List.of()));
        when(users.findAllById(any())).thenReturn(List.of());
    }

    @Test
    void blankFiltersBecomeNullSoNothingIsFilteredOut() {
        service.list(1, 20, "   ", null, "  ");

        // 关键：空串必须转成 null，JPQL 里的 (:action is null or ...) 才会短路放行
        verify(audits).search(isNull(), isNull(), isNull(), any(Pageable.class));
    }

    @Test
    void trimsAndPassesNonBlankFilters() {
        service.list(1, 20, "  admin.user.create  ", 1L, " user:7 ");

        verify(audits)
                .search(
                        org.mockito.ArgumentMatchers.eq("admin.user.create"),
                        org.mockito.ArgumentMatchers.eq(1L),
                        org.mockito.ArgumentMatchers.eq("user:7"),
                        any(Pageable.class));
    }

    @Test
    void pagingIsClampedToSafeRange() {
        AdminAuditPageVO result = service.list(0, 9999, null, null, null);

        assertThat(result.page()).isEqualTo(1); // 0 → 1
        assertThat(result.size()).isEqualTo(100); // 9999 → 100
    }

    @Test
    void operatorNameIsResolvedFromUserTable() {
        when(audits.search(any(), any(), any(), any(Pageable.class)))
                .thenReturn(new PageImpl<>(List.of(log(1L, 6L, "admin.user.create", "user:7"))));
        User admin = new User();
        admin.setId(6L);
        admin.setUsername("admin");
        when(users.findAllById(any())).thenReturn(List.of(admin));

        AdminAuditPageVO result = service.list(1, 20, null, null, null);

        assertThat(result.items()).hasSize(1);
        assertThat(result.items().get(0).operatorName()).isEqualTo("admin");
        assertThat(result.items().get(0).operatorId()).isEqualTo(6L);
    }

    @Test
    void missingOperatorYieldsNullNameInsteadOfFailing() {
        // 操作者账号可能已被硬删，或历史行的 userId 指向不存在的用户
        when(audits.search(any(), any(), any(), any(Pageable.class)))
                .thenReturn(new PageImpl<>(List.of(log(1L, 999L, "admin.user.delete", "user:7"))));

        AdminAuditPageVO result = service.list(1, 20, null, null, null);

        assertThat(result.items().get(0).operatorName()).isNull();
        assertThat(result.items().get(0).operatorId()).isEqualTo(999L);
    }

    @Test
    void nullOperatorIdSkipsTheUserLookupEntirely() {
        when(audits.search(any(), any(), any(), any(Pageable.class)))
                .thenReturn(new PageImpl<>(List.of(log(1L, null, "system.action", null))));

        AdminAuditPageVO result = service.list(1, 20, null, null, null);

        assertThat(result.items().get(0).operatorName()).isNull();
        // 没有有效的 userId 时不该去查用户表
        verify(users, org.mockito.Mockito.never()).findAllById(any());
    }

    @Test
    void detailJsonIsReturnedVerbatim() {
        String detail = "{\"username\":\"u01\"}";
        AuditLog row = log(1L, 6L, "admin.user.create", "user:7");
        row.setDetailJson(detail);
        when(audits.search(any(), any(), any(), any(Pageable.class)))
                .thenReturn(new PageImpl<>(List.of(row)));

        assertThat(service.list(1, 20, null, null, null).items().get(0).detailJson())
                .isEqualTo(detail);
    }

    @Test
    void createdAtFallsBackToZeroWhenNull() {
        AuditLog row = log(1L, 6L, "admin.user.create", "user:7");
        row.setCreatedAt(null);
        when(audits.search(any(), any(), any(), any(Pageable.class)))
                .thenReturn(new PageImpl<>(List.of(row)));

        assertThat(service.list(1, 20, null, null, null).items().get(0).createdAt()).isZero();
    }

    @Test
    void actionsReturnsDistinctSortedNames() {
        when(audits.findAll())
                .thenReturn(
                        List.of(
                                log(1L, 6L, "admin.user.update", "user:7"),
                                log(2L, 6L, "admin.user.create", "user:7"),
                                log(3L, 6L, "admin.user.update", "user:8")));

        assertThat(service.actions()).containsExactly("admin.user.create", "admin.user.update");
    }

    @Test
    void emptyActionsWhenNoLogsYet() {
        when(audits.findAll()).thenReturn(List.of());
        assertThat(service.actions()).isEmpty();
    }

    private static AuditLog log(Long id, Long userId, String action, String target) {
        AuditLog log = new AuditLog();
        log.setId(id);
        log.setUserId(userId);
        log.setAction(action);
        log.setTarget(target);
        log.setDetailJson("{}");
        log.setCreatedAt(1762750000L);
        return log;
    }
}
