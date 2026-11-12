package com.xiaoyi.rag.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.config.XiaoyiProperties;
import com.xiaoyi.rag.model.dto.LoginRequest;
import com.xiaoyi.rag.model.entity.User;
import com.xiaoyi.rag.model.vo.LoginResultVO;
import com.xiaoyi.rag.repository.UserRepository;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

/**
 * H1 门禁：登录必须校验真实口令散列，且错误口令 / 未知账号给出同一个 40100。
 *
 * <p>历史实现把 `demo/demo` 直接当口令接受、把 UUID 存进内存 Map 当令牌，任何知道用户名的人
 * 都能拿到该账号身份。这里逐条钉死：散列必须匹配、未知账号不能自动注册、空白口令一律失败、 令牌里的 userId 必须来自数据库那一行而不是请求体。
 */
class AuthServiceTest {

    private static final String PASSWORD = "correct-horse-battery-staple";

    private final UserRepository users = mock(UserRepository.class);
    private final XiaoyiProperties properties = new XiaoyiProperties();
    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder(4);
    private final TokenService tokens;
    private final AuthService service;

    AuthServiceTest() {
        XiaoyiProperties.Auth auth = new XiaoyiProperties.Auth();
        auth.setJwtSecret("0123456789abcdef0123456789abcdef");
        auth.setIssuer("xiaoyi-rag");
        auth.setTokenTtlSeconds(3600);
        properties.setAuth(auth);
        tokens = new TokenService(properties);
        service = new AuthService(users, tokens, properties);
    }

    private static User user(long id, String username, String hash) {
        User user = new User();
        user.setId(id);
        user.setUsername(username);
        user.setPasswordHash(hash);
        user.setRole("USER");
        return user;
    }

    @BeforeEach
    void seed() {
        when(users.findByUsernameAndDeletedFalse(anyString())).thenReturn(Optional.empty());
        when(users.findByUsernameAndDeletedFalse("alice"))
                .thenReturn(Optional.of(user(7L, "alice", encoder.encode(PASSWORD))));
    }

    @Test
    void correctPasswordIssuesTokenForTheStoredUser() {
        LoginResultVO result = service.login(new LoginRequest("alice", PASSWORD));

        assertThat(result.expiresIn()).isEqualTo(3600);
        assertThat(result.user().id()).isEqualTo(7L);
        assertThat(result.user().username()).isEqualTo("alice");
        assertThat(tokens.verify(result.token())).isEqualTo(7L);
    }

    @Test
    void usernameIsTrimmedBeforeLookup() {
        LoginResultVO result = service.login(new LoginRequest("  alice  ", PASSWORD));

        assertThat(tokens.verify(result.token())).isEqualTo(7L);
    }

    @Test
    void wrongPasswordIsRejectedWithUnauthenticated() {
        assertThatThrownBy(() -> service.login(new LoginRequest("alice", "wrong-password")))
                .isInstanceOf(ApiException.class)
                .hasMessage("用户名或密码错误");

        assertThat(codeOf(() -> service.login(new LoginRequest("alice", "wrong-password"))))
                .isEqualTo(40100);
    }

    @Test
    void unknownAccountIsRejectedAndNeverProvisioned() {
        assertThatThrownBy(() -> service.login(new LoginRequest("mallory", PASSWORD)))
                .isInstanceOf(ApiException.class)
                .hasMessage("用户名或密码错误");

        org.mockito.Mockito.verify(users, org.mockito.Mockito.never())
                .save(org.mockito.ArgumentMatchers.any());
    }

    @Test
    void unknownAccountAndWrongPasswordLookIdentical() {
        String unknown = messageOf(() -> service.login(new LoginRequest("mallory", PASSWORD)));
        String wrong = messageOf(() -> service.login(new LoginRequest("alice", "nope")));

        assertThat(unknown).isEqualTo(wrong).isEqualTo("用户名或密码错误");
    }

    @Test
    void blankOrNullPasswordIsRejected() {
        assertThatThrownBy(() -> service.login(new LoginRequest("alice", null)))
                .isInstanceOf(ApiException.class)
                .hasMessage("用户名或密码错误");
        assertThatThrownBy(() -> service.login(new LoginRequest("alice", "   ")))
                .isInstanceOf(ApiException.class)
                .hasMessage("用户名或密码错误");
    }

    @Test
    void legacyLiteralDemoHashNoLongerAuthenticates() {
        // V6 迁移插入的演示行 password_hash 是字面量 "demo"，不是 BCrypt 摘要。
        when(users.findByUsernameAndDeletedFalse("demo"))
                .thenReturn(Optional.of(user(1L, "demo", "demo")));

        assertThatThrownBy(() -> service.login(new LoginRequest("demo", "demo")))
                .isInstanceOf(ApiException.class)
                .hasMessage("用户名或密码错误");
    }

    @Test
    void tokenSubjectComesFromDatabaseRowNotFromRequest() {
        LoginResultVO result = service.login(new LoginRequest("alice", PASSWORD));

        assertThat(tokens.verify(result.token())).isEqualTo(7L);
        assertThat(result.user().id()).isEqualTo(7L);
    }

    @Test
    void profileRejectsMissingOrInvalidIdentity() {
        assertThatThrownBy(() -> service.profile(null))
                .isInstanceOf(ApiException.class)
                .hasMessage("登录已过期");
        assertThatThrownBy(() -> service.profile(0L))
                .isInstanceOf(ApiException.class)
                .hasMessage("登录已过期");
    }

    @Test
    void profileOfDeletedUserIsRejected() {
        assertThatThrownBy(() -> service.profile(99L))
                .isInstanceOf(ApiException.class)
                .hasMessage("登录已过期");
    }

    @Test
    void profileReturnsTheStoredUsername() {
        when(users.findByIdAndDeletedFalse(7L))
                .thenReturn(Optional.of(user(7L, "alice", encoder.encode(PASSWORD))));

        assertThat(service.profile(7L).username()).isEqualTo("alice");
    }

    @Test
    void loginExposesRoleForFrontendRouting() {
        LoginResultVO user = service.login(new LoginRequest("alice", PASSWORD));
        assertThat(user.user().role()).isEqualTo("USER");

        when(users.findByUsernameAndDeletedFalse("root"))
                .thenReturn(Optional.of(admin(8L, "root", encoder.encode(PASSWORD))));
        assertThat(service.login(new LoginRequest("root", PASSWORD)).user().role())
                .isEqualTo("ADMIN");
    }

    @Test
    void displayNameFallsBackToUsernameWhenNull() {
        LoginResultVO result = service.login(new LoginRequest("alice", PASSWORD));
        assertThat(result.user().displayName()).isEqualTo("alice");
    }

    @Test
    void softDeletedAccountCannotLogIn() {
        // 查询已带 deleted = false，软删行查不到 → 与「未知账号」同一条错误
        when(users.findByUsernameAndDeletedFalse("ghost")).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.login(new LoginRequest("ghost", PASSWORD)))
                .isInstanceOf(ApiException.class)
                .hasMessage("用户名或密码错误");
    }

    private static User admin(long id, String username, String hash) {
        User user = user(id, username, hash);
        user.setRole("ADMIN");
        return user;
    }

    private static String messageOf(Runnable action) {
        try {
            action.run();
            throw new AssertionError("应当抛出 ApiException");
        } catch (ApiException ex) {
            return ex.getMessage();
        }
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
