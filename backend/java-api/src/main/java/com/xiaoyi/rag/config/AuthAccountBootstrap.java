package com.xiaoyi.rag.config;

import com.xiaoyi.rag.model.entity.User;
import com.xiaoyi.rag.repository.UserRepository;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.env.Environment;
import org.springframework.core.env.Profiles;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * Optional environment-controlled provisioning, never an HTTP registration endpoint.
 *
 * <p>V11 起两个 bootstrap 账号的角色不同：
 *
 * <ul>
 *   <li><b>主账号</b>（{@code AUTH_BOOTSTRAP_USERNAME}）→ {@code ADMIN}，即管理端唯一账号。 已存在但还不是 ADMIN
 *       时幂等升级（部署可能先用旧版本建过这个号）。
 *   <li><b>次账号</b>（{@code AUTH_SECONDARY_BOOTSTRAP_USERNAME}）→ {@code USER}，用于 H2 的 A/B 隔离测试。
 * </ul>
 *
 * <p>V6 迁移插入的 demo 行（{@code password_hash} 是字面量 {@code 'demo'}）只允许在显式 demo profile 下被 收养改密，且永远是
 * {@code USER} —— demo 账号不许升成管理员。
 */
@Component
public class AuthAccountBootstrap implements ApplicationRunner {
    private final UserRepository users;
    private final XiaoyiProperties.Auth auth;
    private final boolean demoProfile;
    private final BCryptPasswordEncoder passwords = new BCryptPasswordEncoder(12);

    public AuthAccountBootstrap(
            UserRepository users, XiaoyiProperties properties, Environment env) {
        this.users = users;
        auth = properties.getAuth();
        demoProfile = env.acceptsProfiles(Profiles.of("demo"));
    }

    @Override
    @Transactional
    public void run(ApplicationArguments args) {
        provision(auth.getBootstrapUsername(), auth.getBootstrapPassword(), "ADMIN");
        provision(
                auth.getSecondaryBootstrapUsername(), auth.getSecondaryBootstrapPassword(), "USER");
    }

    private void provision(String username, String password, String role) {
        boolean hasName = username != null && !username.isBlank();
        boolean hasPassword = password != null && !password.isBlank();
        if (!hasName && !hasPassword) {
            return;
        }
        if (!hasName
                || !hasPassword
                || username.trim().length() > 64
                || password.length() < 12
                || password.getBytes(java.nio.charset.StandardCharsets.UTF_8).length > 72) {
            throw new IllegalStateException(
                    "Bootstrap requires username (1..64 chars) and password (12..72 UTF-8 bytes)");
        }
        User user = users.findAnyByUsername(username.trim()).orElse(null);
        if (user != null) {
            // Historical migrations seeded the literal 'demo', which is not a password hash.
            // Only an explicit demo deployment may adopt that row using an operator-supplied
            // password.
            if ("demo".equals(user.getPasswordHash()) && demoProfile) {
                user.setPasswordHash(passwords.encode(password));
                users.save(user);
            }
            // 幂等升级：主账号在旧版本里被建成 USER，这里补成 ADMIN。
            // 只升不降（role 已是 ADMIN 就不动），重跑多少次结果都一样。
            if ("ADMIN".equals(role) && !"ADMIN".equals(user.getRole())) {
                user.setRole("ADMIN");
                users.save(user);
            }
            return;
        }
        user = new User();
        user.setUsername(username.trim());
        user.setPasswordHash(passwords.encode(password));
        user.setRole(role);
        user.setDeleted(Boolean.FALSE);
        users.save(user);
    }
}
