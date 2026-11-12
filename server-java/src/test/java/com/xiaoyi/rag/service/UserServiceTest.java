package com.xiaoyi.rag.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.model.dto.AdminUserCreateRequest;
import com.xiaoyi.rag.model.dto.AdminUserPasswordRequest;
import com.xiaoyi.rag.model.dto.AdminUserUpdateRequest;
import com.xiaoyi.rag.model.entity.AuditLog;
import com.xiaoyi.rag.model.entity.User;
import com.xiaoyi.rag.model.vo.AdminUserItemVO;
import com.xiaoyi.rag.repository.AuditLogRepository;
import com.xiaoyi.rag.repository.UserRepository;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.Pageable;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

/**
 * 06 号设计方案 §9.1 的核心不变量测试。
 *
 * <p>这里钉的是三件「错了就是安全问题」的事：
 *
 * <ol>
 *   <li>创建的账号永远是 USER —— 没有任何参数能让调用方造出第二个管理员；
 *   <li>管理员不能对自己下手（改/重置/删），否则唯一管理员能把系统锁死；
 *   <li>软删的账号在业务语义上就是「不存在」，不是「存在但标记了」。
 * </ol>
 *
 * <p>另外还钉密码长度按 <b>UTF-8 字节</b> 判：用字符数判会放行超过 72 字节的口令，bcrypt 会静默截断。
 */
class UserServiceTest {

    private static final long ADMIN_ID = 1L;
    private static final String PASSWORD = "correct-horse-battery";

    private final UserRepository users = mock(UserRepository.class);
    private final AuditLogRepository audits = mock(AuditLogRepository.class);
    private final UserService service = new UserService(users, audits);
    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder(4);

    @BeforeEach
    void defaults() {
        when(users.existsByUsername(anyString())).thenReturn(false);
        when(users.findByIdAndDeletedFalse(any())).thenReturn(Optional.empty());
        when(audits.save(any())).thenAnswer(inv -> inv.getArgument(0));
    }

    /* ------------------------------------------------------- 创建 */

    @Test
    void createAlwaysProducesPlainUserEvenIfRequestSmugglesRole() {
        // record 没有 role 字段，所以「传 role」在 JSON 层就已经被 additionalProperties: false 挡掉；
        // 这里验证的是第二道闸：service 落库时 role 写死 USER。
        AdminUserItemVO created =
                service.create(ADMIN_ID, new AdminUserCreateRequest("u01", PASSWORD, "张三"));

        assertThat(created.role()).isEqualTo("USER");
        assertThat(created.username()).isEqualTo("u01");
        assertThat(created.deleted()).isFalse();
    }

    @Test
    void explicitRoleInRequestIsRejectedNotSilentlyIgnored() {
        // 全局 Jackson 忽略未知字段；若 DTO 不声明 role，传 {"role":"ADMIN"} 会被静默丢弃，
        // 结果虽然是 USER，但契约承诺的 40001 没发生 —— 调用方会误以为设置成功了。
        assertThatThrownBy(
                        () ->
                                service.create(
                                        ADMIN_ID,
                                        new AdminUserCreateRequest("u02", PASSWORD, null, "ADMIN")))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("不能指定角色");
        assertThat(
                        codeOf(
                                () ->
                                        service.create(
                                                ADMIN_ID,
                                                new AdminUserCreateRequest(
                                                        "u02", PASSWORD, null, "ADMIN"))))
                .isEqualTo(40001);

        // 一个都没落下：被拒的请求不写库、不写审计
        verify(users, never()).save(any());
        verify(audits, never()).save(any());
    }

    @Test
    void blankRoleIsTreatedAsNotSpecified() {
        // role 传 null 或空白都算「没指定」，正常创建
        assertThat(
                        service.create(
                                        ADMIN_ID,
                                        new AdminUserCreateRequest("u03", PASSWORD, null, null))
                                .role())
                .isEqualTo("USER");
        assertThat(
                        service.create(
                                        ADMIN_ID,
                                        new AdminUserCreateRequest("u04", PASSWORD, null, "  "))
                                .role())
                .isEqualTo("USER");
    }

    @Test
    void createHashesPasswordAndNeverReturnsIt() {
        service.create(ADMIN_ID, new AdminUserCreateRequest("u01", PASSWORD, null));

        ArgumentCaptor<User> saved = ArgumentCaptor.forClass(User.class);
        verify(users).save(saved.capture());
        assertThat(saved.getValue().getPasswordHash()).isNotEqualTo(PASSWORD);
        assertThat(
                        new BCryptPasswordEncoder()
                                .matches(PASSWORD, saved.getValue().getPasswordHash()))
                .isTrue();
    }

    @Test
    void duplicateUsernameIsRejectedEvenWhenOnlySoftDeletedRowHoldsIt() {
        // 软删行的 username 仍然占着唯一键 —— 放过去会撞 DB 唯一约束变成 50000。
        when(users.existsByUsername("u01")).thenReturn(true);

        assertThatThrownBy(
                        () ->
                                service.create(
                                        ADMIN_ID,
                                        new AdminUserCreateRequest("u01", PASSWORD, null)))
                .isInstanceOf(ApiException.class)
                .hasMessage("用户名已存在");
        assertThat(
                        codeOf(
                                () ->
                                        service.create(
                                                ADMIN_ID,
                                                new AdminUserCreateRequest("u01", PASSWORD, null))))
                .isEqualTo(40905);
    }

    @Test
    void blankDisplayNameIsStoredAsNullSoUiFallsBackToUsername() {
        service.create(ADMIN_ID, new AdminUserCreateRequest("u01", PASSWORD, "   "));

        ArgumentCaptor<User> saved = ArgumentCaptor.forClass(User.class);
        verify(users).save(saved.capture());
        assertThat(saved.getValue().getDisplayName()).isNull();
    }

    @Test
    void usernameMustMatchTheContractPattern() {
        assertThatThrownBy(
                        () ->
                                service.create(
                                        ADMIN_ID, new AdminUserCreateRequest("张三", PASSWORD, null)))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("用户名");
        assertThatThrownBy(
                        () ->
                                service.create(
                                        ADMIN_ID,
                                        new AdminUserCreateRequest("a b", PASSWORD, null)))
                .isInstanceOf(ApiException.class);
        verify(users, never()).save(any());
    }

    @Test
    void passwordLengthIsMeasuredInUtf8BytesNotCharacters() {
        // 11 字节：太短
        assertThatThrownBy(
                        () ->
                                service.create(
                                        ADMIN_ID,
                                        new AdminUserCreateRequest("u01", "12345678901", null)))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("12-72");

        // 12 字节：刚好通过
        assertThat(
                        service.create(
                                        ADMIN_ID,
                                        new AdminUserCreateRequest("u02", "123456789012", null))
                                .username())
                .isEqualTo("u02");

        // 25 个中文 = 75 字节：字符数只有 25，但按字节已经超 72
        String tooLongInBytes = "密".repeat(25);
        assertThatThrownBy(
                        () ->
                                service.create(
                                        ADMIN_ID,
                                        new AdminUserCreateRequest("u03", tooLongInBytes, null)))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("12-72");

        // 24 个中文 = 72 字节：字节口径下刚好通过
        assertThat(
                        service.create(
                                        ADMIN_ID,
                                        new AdminUserCreateRequest("u04", "密".repeat(24), null))
                                .username())
                .isEqualTo("u04");
    }

    /* --------------------------------------------------- 管理员自保 */

    @Test
    void adminCannotEditOwnRow() {
        assertThatThrownBy(
                        () ->
                                service.update(
                                        ADMIN_ID, ADMIN_ID, new AdminUserUpdateRequest("hacked")))
                .isInstanceOf(ApiException.class)
                .hasMessage("不能修改管理员账号");
        assertThat(
                        codeOf(
                                () ->
                                        service.update(
                                                ADMIN_ID,
                                                ADMIN_ID,
                                                new AdminUserUpdateRequest("x"))))
                .isEqualTo(40906);
        verify(users, never()).save(any());
    }

    @Test
    void adminCannotResetOwnPassword() {
        assertThatThrownBy(
                        () ->
                                service.updatePassword(
                                        ADMIN_ID, ADMIN_ID, new AdminUserPasswordRequest(PASSWORD)))
                .isInstanceOf(ApiException.class)
                .hasMessage("不能重置管理员账号的密码");
        assertThat(
                        codeOf(
                                () ->
                                        service.updatePassword(
                                                ADMIN_ID,
                                                ADMIN_ID,
                                                new AdminUserPasswordRequest(PASSWORD))))
                .isEqualTo(40906);
    }

    @Test
    void adminCannotDeleteSelf() {
        assertThatThrownBy(() -> service.delete(ADMIN_ID, ADMIN_ID))
                .isInstanceOf(ApiException.class)
                .hasMessage("不能删除管理员账号");
        verify(users, never()).save(any());
    }

    /* ------------------------------------------------ 软删即不存在 */

    @Test
    void operatingOnSoftDeletedUserLooksLikeNotFound() {
        // delete 与 update 都走 requireActive → 软删行查不到 → 40409
        assertThatThrownBy(() -> service.delete(ADMIN_ID, 42L))
                .isInstanceOf(ApiException.class)
                .hasMessage("用户不存在");
        assertThat(codeOf(() -> service.delete(ADMIN_ID, 42L))).isEqualTo(40409);

        assertThatThrownBy(() -> service.update(ADMIN_ID, 42L, new AdminUserUpdateRequest("nope")))
                .isInstanceOf(ApiException.class)
                .hasMessage("用户不存在");

        assertThatThrownBy(
                        () ->
                                service.updatePassword(
                                        ADMIN_ID, 42L, new AdminUserPasswordRequest(PASSWORD)))
                .isInstanceOf(ApiException.class)
                .hasMessage("用户不存在");
    }

    @Test
    void deleteOnlyFlipsTheSoftDeleteFlag() {
        User target = user(7L, "u01", "USER", false);
        when(users.findByIdAndDeletedFalse(7L)).thenReturn(Optional.of(target));

        service.delete(ADMIN_ID, 7L);

        ArgumentCaptor<User> saved = ArgumentCaptor.forClass(User.class);
        verify(users).save(saved.capture());
        assertThat(saved.getValue().getDeleted()).isTrue();
        // 硬删绝不能发生：历史会话与资料的归属还挂在 id 上
        verify(users, never()).deleteById(any());
        verify(users, never()).delete(any());
    }

    /* ------------------------------------------------------ 审计 */

    @Test
    void everyMutationWritesAnAuditRowWithoutSecrets() {
        User target = user(7L, "u01", "USER", false);
        when(users.findByIdAndDeletedFalse(7L)).thenReturn(Optional.of(target));

        service.create(ADMIN_ID, new AdminUserCreateRequest("u02", PASSWORD, "李四"));
        service.update(ADMIN_ID, 7L, new AdminUserUpdateRequest("王五"));
        service.updatePassword(ADMIN_ID, 7L, new AdminUserPasswordRequest(PASSWORD));
        service.delete(ADMIN_ID, 7L);

        ArgumentCaptor<AuditLog> logs = ArgumentCaptor.forClass(AuditLog.class);
        verify(audits, org.mockito.Mockito.times(4)).save(logs.capture());
        List<String> actions = logs.getAllValues().stream().map(AuditLog::getAction).toList();

        assertThat(actions)
                .containsExactly(
                        "admin.user.create",
                        "admin.user.update",
                        "admin.user.reset-password",
                        "admin.user.delete");

        // 审计里绝不能出现口令：detail 只记「变了」，不记值
        assertThat(logs.getAllValues())
                .allSatisfy(
                        log -> {
                            assertThat(log.getDetailJson()).doesNotContain(PASSWORD);
                            assertThat(log.getUserId()).isEqualTo(ADMIN_ID);
                        });
    }

    /* ------------------------------------------------------ 列表 */

    @Test
    void listClampsPagingAndPassesKeywordThrough() {
        Page<User> page = new PageImpl<>(List.of(user(2L, "u01", "USER", false)));
        when(users.search(any(), org.mockito.ArgumentMatchers.anyBoolean(), any(Pageable.class)))
                .thenReturn(page);

        var result = service.list(0, 9999, "  u0  ", false);

        assertThat(result.page()).isEqualTo(1); // page 0 被夹到 1
        assertThat(result.size()).isEqualTo(100); // size 9999 被夹到 100
        assertThat(result.total()).isEqualTo(1);
        assertThat(result.items()).hasSize(1);

        ArgumentCaptor<String> keyword = ArgumentCaptor.forClass(String.class);
        verify(users)
                .search(
                        keyword.capture(),
                        org.mockito.ArgumentMatchers.eq(false),
                        any(Pageable.class));
        assertThat(keyword.getValue()).isEqualTo("u0"); // 前后空白被 trim
    }

    @Test
    void blankKeywordBecomesNullSoNoFilterIsApplied() {
        when(users.search(any(), org.mockito.ArgumentMatchers.anyBoolean(), any(Pageable.class)))
                .thenReturn(new PageImpl<>(List.of()));

        service.list(1, 20, "   ", false);

        verify(users)
                .search(
                        org.mockito.ArgumentMatchers.isNull(),
                        org.mockito.ArgumentMatchers.eq(false),
                        any(Pageable.class));
    }

    @Test
    void listMarksSoftDeletedRows() {
        User deleted = user(9L, "gone", "USER", true);
        when(users.search(any(), org.mockito.ArgumentMatchers.anyBoolean(), any(Pageable.class)))
                .thenReturn(new PageImpl<>(List.of(deleted)));

        var result = service.list(1, 20, null, true);

        assertThat(result.items().get(0).deleted()).isTrue();
    }

    /* ------------------------------------------------------ 工具 */

    private static User user(long id, String username, String role, boolean deleted) {
        User user = new User();
        user.setId(id);
        user.setUsername(username);
        user.setPasswordHash("$2a$04$abcdefghijklmnopqrstuv");
        user.setRole(role);
        user.setDeleted(deleted);
        user.setCreatedAt(1762750000L);
        return user;
    }

    private static int codeOf(Runnable action) {
        try {
            action.run();
            throw new AssertionError("应当抛出 ApiException");
        } catch (ApiException ex) {
            return ex.getCode();
        }
    }
}
