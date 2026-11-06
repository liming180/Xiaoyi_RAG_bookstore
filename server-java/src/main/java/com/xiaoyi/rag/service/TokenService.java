package com.xiaoyi.rag.service;

import com.auth0.jwt.JWT;
import com.auth0.jwt.JWTVerifier;
import com.auth0.jwt.algorithms.Algorithm;
import com.auth0.jwt.exceptions.JWTVerificationException;
import com.xiaoyi.rag.config.XiaoyiProperties;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.UUID;
import org.springframework.stereotype.Service;

/**
 * Signed bearer sessions expire at the configured TTL; rotation of the secret revokes all sessions.
 */
@Service
public class TokenService {
    private final Algorithm algorithm;
    private final JWTVerifier verifier;
    private final String issuer;
    private final long ttl;

    public TokenService(XiaoyiProperties properties) {
        XiaoyiProperties.Auth auth = properties.getAuth();
        String secret = auth.getJwtSecret();
        if (secret == null
                || secret.isBlank()
                || secret.getBytes(StandardCharsets.UTF_8).length < 32) {
            throw new IllegalStateException("AUTH_JWT_SECRET must contain at least 32 UTF-8 bytes");
        }
        if (auth.getIssuer() == null
                || auth.getIssuer().isBlank()
                || auth.getTokenTtlSeconds() < 1) {
            throw new IllegalStateException("JWT issuer and positive token TTL are required");
        }
        algorithm = Algorithm.HMAC256(secret);
        issuer = auth.getIssuer();
        ttl = auth.getTokenTtlSeconds();
        verifier = JWT.require(algorithm).withIssuer(issuer).withClaimPresence("exp").build();
    }

    public String issue(long userId) {
        if (userId <= 0) {
            throw new IllegalArgumentException("Positive user id required");
        }
        Instant now = Instant.now();
        return JWT.create()
                .withIssuer(issuer)
                .withSubject(Long.toString(userId))
                .withIssuedAt(now)
                .withExpiresAt(now.plusSeconds(ttl))
                .withJWTId(UUID.randomUUID().toString())
                .sign(algorithm);
    }

    public Long verify(String token) {
        try {
            long id = Long.parseLong(verifier.verify(token).getSubject());
            return id > 0 ? id : null;
        } catch (JWTVerificationException | IllegalArgumentException ex) {
            return null;
        }
    }
}
