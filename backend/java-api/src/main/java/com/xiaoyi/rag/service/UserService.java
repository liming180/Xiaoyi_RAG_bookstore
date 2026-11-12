package com.xiaoyi.rag.service;

import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.model.dto.AdminUserCreateRequest;
import com.xiaoyi.rag.model.dto.AdminUserPasswordRequest;
import com.xiaoyi.rag.model.dto.AdminUserUpdateRequest;
import com.xiaoyi.rag.model.entity.AuditLog;
import com.xiaoyi.rag.model.entity.User;
import com.xiaoyi.rag.model.vo.AdminUserItemVO;
import com.xiaoyi.rag.model.vo.AdminUserPageVO;
import com.xiaoyi.rag.repository.AuditLogRepository;
import com.xiaoyi.rag.repository.UserRepository;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 管理端用户管理：增、改、删、重置密码、分页列表。
 *
 * <p>三条不变量集中在这里（控制器只做参数透传），任何绕过 HTTP 层的调用同样受约束：
 *
 * <ol>
 *   <li><b>唯一 ADMIN</b>：{@link #create} 强制 {@code role=USER}，没有任何参数能创建第二个管理员。
 *   <li><b>管理员不可自我毁灭</b>：{@link #update}、{@link #updatePassword}、{@link #delete} 对「操作者自己」一律 {@code
 *       40906}。管理员不能改自己、不能重置自己密码、不能删自己 —— 否则唯一管理员能把系统锁死。
 *   <li><b>软删即不存在</b>：目标已软删时按 {@code 40409「用户不存在」} 处理，不给「这个号存在但被删了」的信号。
 * </ol>
 *
 * <p>密码长度按 <b>UTF-8 字节</b>校验（12–72），与 {@code AuthAccountBootstrap} 的既有口径一致： bcrypt 只处理前 72
 * 字节，用字符数判会让中文口令悄悄被截断。
 */
@Service
public class UserService {

    private static final String ROLE_ADMIN = "ADMIN";
    private static final String ROLE_USER = "USER";
    private static final int PASSWORD_MIN_BYTES = 12;
    private static final int PASSWORD_MAX_BYTES = 72;
    private static final int MAX_PAGE_SIZE = 100;

    private final UserRepository users;
    private final AuditLogRepository audits;
    private final BCryptPasswordEncoder passwords = new BCryptPasswordEncoder(12);

    public UserService(UserRepository users, AuditLogRepository audits) {
        this.users = users;
        this.audits = audits;
    }

    /**
     * 分页列表。
     *
     * @param keyword 空/null 表示不过滤；否则 username 前缀 + displayName 包含匹配
     * @param includeDeleted 仅排障用，默认 false
     */
    @Transactional(readOnly = true)
    public AdminUserPageVO list(int page, int size, String keyword, boolean includeDeleted) {
        int safePage = Math.max(page, 1);
        // 上限 100：再大就退化成「一次拉全表」，管理端没有这个需求。
        int safeSize = Math.min(Math.max(size, 1), MAX_PAGE_SIZE);
        String safeKeyword = keyword == null || keyword.isBlank() ? null : keyword.trim();

        Pageable pageable = PageRequest.of(safePage - 1, safeSize);
        Page<User> result = users.search(safeKeyword, includeDeleted, pageable);
        List<AdminUserItemVO> items = result.getContent().stream().map(this::toItem).toList();
        return new AdminUserPageVO(items, result.getTotalElements(), safePage, safeSize);
    }

    /** 新建普通用户。角色强制 USER，{@code role} 参数不存在于此签名里。 */
    @Transactional
    public AdminUserItemVO create(Long operatorId, AdminUserCreateRequest request) {
        // 契约承诺「传 role 就是 40001」，而全局 Jackson 会静默丢掉未知字段。
        // 这里显式拒一次，否则请求方会以为「指定 ADMIN 成功了」（实际落库仍是 USER）。
        if (request.role() != null && !request.role().isBlank()) {
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "不能指定角色，新建账号一律为普通用户");
        }
        String username = request.username().trim();
        requireUsernameShape(username);
        requirePasswordBytes(request.password(), "密码不能为空");

        // 重名检查连软删行一起挡：username 的唯一键在软删行上仍然占着，
        // 放过去会在 insert 时撞唯一键，变成 50000 而不是有意义的 40905。
        if (users.existsByUsername(username)) {
            throw new ApiException(
                    ErrorCode.USERNAME_DUPLICATE.getCode(),
                    ErrorCode.USERNAME_DUPLICATE.getDefaultMessage());
        }

        User user = new User();
        user.setUsername(username);
        user.setDisplayName(normalizeDisplayName(request.displayName()));
        user.setPasswordHash(passwords.encode(request.password()));
        user.setRole(ROLE_USER);
        user.setDeleted(Boolean.FALSE);
        users.save(user);

        audit(operatorId, "admin.user.create", user.getId(), "{\"username\":\"" + username + "\"}");
        return toItem(user);
    }

    /** 改显示名。不含密码。 */
    @Transactional
    public AdminUserItemVO update(Long operatorId, Long id, AdminUserUpdateRequest request) {
        requireNotSelf(operatorId, id, "不能修改管理员账号");
        User user = requireActive(id);

        user.setDisplayName(normalizeDisplayName(request.displayName()));
        users.save(user);

        audit(operatorId, "admin.user.update", id, "{\"displayName\":\"changed\"}");
        return toItem(user);
    }

    /** 重置密码。独立端点，独立审计动作。 */
    @Transactional
    public AdminUserItemVO updatePassword(
            Long operatorId, Long id, AdminUserPasswordRequest request) {
        requireNotSelf(operatorId, id, "不能重置管理员账号的密码");
        User user = requireActive(id);
        requirePasswordBytes(request.newPassword(), "密码不能为空");

        user.setPasswordHash(passwords.encode(request.newPassword()));
        users.save(user);

        // 只记「密码变了」，绝不记明文/哈希。
        audit(operatorId, "admin.user.reset-password", id, "{\"password\":\"changed\"}");
        return toItem(user);
    }

    /** 软删。删完立即不能登录；历史会话与资料保留。 */
    @Transactional
    public void delete(Long operatorId, Long id) {
        requireNotSelf(operatorId, id, "不能删除管理员账号");
        User user = requireActive(id);

        user.setDeleted(Boolean.TRUE);
        users.save(user);

        audit(operatorId, "admin.user.delete", id, "{\"deleted\":true}");
    }

    /* --------------------------------------------------------------- 内部 */

    private User requireActive(Long id) {
        return users.findByIdAndDeletedFalse(id)
                .orElseThrow(
                        () ->
                                new ApiException(
                                        ErrorCode.USER_NOT_FOUND.getCode(),
                                        ErrorCode.USER_NOT_FOUND.getDefaultMessage()));
    }

    /** 对自己操作 → 40906。id 或 operatorId 为 null 时不做判（交给 requireActive 报 40409）。 */
    private void requireNotSelf(Long operatorId, Long id, String message) {
        if (operatorId != null && id != null && operatorId.equals(id)) {
            throw new ApiException(ErrorCode.ADMIN_ACCOUNT_PROTECTED.getCode(), message);
        }
    }

    /** 用户名形状：1–64 字符，字母数字下划线。规则与契约 schema 的 pattern 一致。 */
    private void requireUsernameShape(String username) {
        if (username.isEmpty() || username.length() > 64 || !username.matches("^[a-zA-Z0-9_]+$")) {
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "用户名需为 1-64 位字母、数字或下划线");
        }
    }

    /**
     * 密码按 UTF-8 字节校验长度。
     *
     * <p>为什么不用 {@code String.length()}：中文一个字 3 字节，12 个中文是 36 字符 36 字节， 而 30 个中文是 30 字符 90 字节 ——
     * 用字符数判会放行超 72 字节的口令，bcrypt 会静默截断。
     */
    private void requirePasswordBytes(String password, String blankMessage) {
        if (password == null || password.isBlank()) {
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), blankMessage);
        }
        int bytes = password.getBytes(StandardCharsets.UTF_8).length;
        if (bytes < PASSWORD_MIN_BYTES || bytes > PASSWORD_MAX_BYTES) {
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "密码长度需为 12-72 个字节（UTF-8）");
        }
    }

    /** 空串 → NULL，让列表回退显示 username。 */
    private String normalizeDisplayName(String displayName) {
        return displayName == null || displayName.isBlank() ? null : displayName.trim();
    }

    private void audit(Long operatorId, String action, Long targetId, String detailJson) {
        AuditLog log = new AuditLog();
        log.setUserId(operatorId);
        log.setAction(action);
        log.setTarget("user:" + targetId);
        log.setDetailJson(detailJson);
        audits.save(log);
    }

    private AdminUserItemVO toItem(User user) {
        return new AdminUserItemVO(
                user.getId(),
                user.getUsername(),
                user.getDisplayName(),
                user.getRole(),
                Boolean.TRUE.equals(user.getDeleted()),
                user.getCreatedAt() == null ? 0L : user.getCreatedAt());
    }

    /** 供鉴权与测试使用：某用户是否为管理员。 */
    @Transactional(readOnly = true)
    public boolean isAdmin(Long userId) {
        if (userId == null || userId <= 0) {
            return false;
        }
        return users.findByIdAndDeletedFalse(userId)
                .map(user -> ROLE_ADMIN.equals(user.getRole()))
                .orElse(false);
    }
}
