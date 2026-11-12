package com.xiaoyi.rag.service;

import com.xiaoyi.rag.model.entity.AuditLog;
import com.xiaoyi.rag.model.entity.User;
import com.xiaoyi.rag.model.vo.AdminAuditItemVO;
import com.xiaoyi.rag.model.vo.AdminAuditPageVO;
import com.xiaoyi.rag.repository.AuditLogRepository;
import com.xiaoyi.rag.repository.UserRepository;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Collectors;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 管理端 · 审计查询。
 *
 * <p>只读服务：审计表是「谁在什么时候对谁做了什么」的账本，这个类**不提供任何写入口**， 也不提供删除——审计日志能被管理端改掉就失去了意义。写入只发生在 {@link
 * UserService} 的业务动作里。
 */
@Service
public class AuditService {

    private static final int MAX_PAGE_SIZE = 100;

    private final AuditLogRepository audits;
    private final UserRepository users;

    public AuditService(AuditLogRepository audits, UserRepository users) {
        this.audits = audits;
        this.users = users;
    }

    /**
     * 分页查询审计日志。
     *
     * @param action 动作名精确匹配；空/null 表示不过滤
     * @param operatorId 操作者 id 精确匹配；null 表示不过滤
     * @param keyword target 字段包含匹配；空/null 表示不过滤
     */
    @Transactional(readOnly = true)
    public AdminAuditPageVO list(
            int page, int size, String action, Long operatorId, String keyword) {
        int safePage = Math.max(page, 1);
        int safeSize = Math.min(Math.max(size, 1), MAX_PAGE_SIZE);
        String safeAction = blankToNull(action);
        String safeKeyword = blankToNull(keyword);

        Pageable pageable = PageRequest.of(safePage - 1, safeSize);
        Page<AuditLog> result = audits.search(safeAction, operatorId, safeKeyword, pageable);
        List<AuditLog> rows = result.getContent();

        Map<Long, String> names = resolveOperatorNames(rows);
        List<AdminAuditItemVO> items =
                rows.stream()
                        .map(
                                log ->
                                        new AdminAuditItemVO(
                                                log.getId(),
                                                log.getUserId(),
                                                log.getUserId() == null
                                                        ? null
                                                        : names.get(log.getUserId()),
                                                log.getAction(),
                                                log.getTarget(),
                                                log.getDetailJson(),
                                                log.getCreatedAt() == null
                                                        ? 0L
                                                        : log.getCreatedAt()))
                        .toList();

        return new AdminAuditPageVO(items, result.getTotalElements(), safePage, safeSize);
    }

    /** 当前库里出现过的动作名，给前端下拉框用（不硬编码在页面里，新增动作自动出现）。 */
    @Transactional(readOnly = true)
    public List<String> actions() {
        return audits.findAll().stream()
                .map(AuditLog::getAction)
                .filter(Objects::nonNull)
                .distinct()
                .sorted()
                .toList();
    }

    /**
     * 批量解析操作者用户名。
     *
     * <p>一次 {@code findAllById} 而不是逐行查：审计页一屏最多 100 行，逐行查会变成 100 次往返。 查不到就是
     * null（历史行的操作者可能已不存在），前端显示「—」。
     */
    private Map<Long, String> resolveOperatorNames(List<AuditLog> rows) {
        Set<Long> ids =
                rows.stream()
                        .map(AuditLog::getUserId)
                        .filter(Objects::nonNull)
                        .collect(Collectors.toSet());
        if (ids.isEmpty()) {
            return Map.of();
        }
        return users.findAllById(ids).stream()
                .collect(Collectors.toMap(User::getId, User::getUsername, (a, b) -> a));
    }

    private static String blankToNull(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }
}
