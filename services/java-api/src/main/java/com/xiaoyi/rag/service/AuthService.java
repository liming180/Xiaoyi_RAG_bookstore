package com.xiaoyi.rag.service;

import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.config.XiaoyiProperties;
import com.xiaoyi.rag.model.dto.LoginRequest;
import com.xiaoyi.rag.model.entity.User;
import com.xiaoyi.rag.model.vo.LoginResultVO;
import com.xiaoyi.rag.model.vo.UserInfoVO;
import com.xiaoyi.rag.repository.UserRepository;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

/** Password authentication; login never provisions an account. */
@Service
public class AuthService {
    private final UserRepository users;
    private final TokenService tokens;
    private final BCryptPasswordEncoder passwords = new BCryptPasswordEncoder(12);
    private final String dummyHash = passwords.encode("non-account-timing-check");
    private final long ttl;

    public AuthService(UserRepository users, TokenService tokens, XiaoyiProperties properties) {
        this.users = users;
        this.tokens = tokens;
        this.ttl = properties.getAuth().getTokenTtlSeconds();
    }

    /**
     * 口令登录。
     *
     * <p><b>软删账号走「未知账号」这条路</b>：查询用 {@code findByUsernameAndDeletedFalse}，所以 {@code deleted=1}
     * 的行根本查不到 → 落到 dummyHash 的假校验 → 回同一个「用户名或密码错误」。 这样删号即封停，且不泄漏「这个账号曾经存在」。
     */
    public LoginResultVO login(LoginRequest request) {
        User user = users.findByUsernameAndDeletedFalse(request.username().trim()).orElse(null);
        String hash = user == null ? dummyHash : user.getPasswordHash();
        String password = request.password();
        boolean matches = passwords.matches(password == null ? "" : password, hash);
        if (user == null || password == null || password.isBlank() || !matches) {
            throw new ApiException(40100, "用户名或密码错误");
        }
        return new LoginResultVO(tokens.issue(user.getId()), ttl, toUserInfo(user));
    }

    public UserInfoVO profile(Long id) {
        if (id == null || id <= 0) {
            throw new ApiException(40100, "登录已过期");
        }
        return toUserInfo(
                users.findByIdAndDeletedFalse(id)
                        .orElseThrow(() -> new ApiException(40100, "登录已过期")));
    }

    private UserInfoVO toUserInfo(User user) {
        // displayName 为空时回退 username：前端列表与顶栏都直接展示这个值，
        // 回 null 会让老数据（V11 之前的行）在界面上显示成空白。
        String displayName =
                user.getDisplayName() == null || user.getDisplayName().isBlank()
                        ? user.getUsername()
                        : user.getDisplayName();
        return new UserInfoVO(user.getId(), user.getUsername(), displayName, user.getRole());
    }
}
