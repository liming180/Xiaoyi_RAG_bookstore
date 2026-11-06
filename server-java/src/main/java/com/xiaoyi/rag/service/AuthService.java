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

    public LoginResultVO login(LoginRequest request) {
        User user = users.findByUsername(request.username().trim()).orElse(null);
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
        return toUserInfo(users.findById(id).orElseThrow(() -> new ApiException(40100, "登录已过期")));
    }

    private UserInfoVO toUserInfo(User user) {
        return new UserInfoVO(user.getId(), user.getUsername(), user.getUsername());
    }
}
