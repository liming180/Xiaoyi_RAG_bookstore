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

/** Optional environment-controlled provisioning, never an HTTP registration endpoint. */
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
        provision(auth.getBootstrapUsername(), auth.getBootstrapPassword());
        provision(auth.getSecondaryBootstrapUsername(), auth.getSecondaryBootstrapPassword());
    }

    private void provision(String username, String password) {
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
        User user = users.findByUsername(username.trim()).orElse(null);
        if (user != null) {
            // Historical migrations seeded the literal 'demo', which is not a password hash.
            // Only an explicit demo deployment may adopt that row using an operator-supplied
            // password.
            if ("demo".equals(user.getPasswordHash()) && demoProfile) {
                user.setPasswordHash(passwords.encode(password));
                users.save(user);
            }
            return;
        }
        user = new User();
        user.setUsername(username.trim());
        user.setPasswordHash(passwords.encode(password));
        user.setRole("USER");
        users.save(user);
    }
}
