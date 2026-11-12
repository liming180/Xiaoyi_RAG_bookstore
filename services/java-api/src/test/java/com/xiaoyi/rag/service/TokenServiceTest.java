package com.xiaoyi.rag.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.auth0.jwt.JWT;
import com.auth0.jwt.algorithms.Algorithm;
import com.xiaoyi.rag.config.XiaoyiProperties;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import org.junit.jupiter.api.Test;

/**
 * H1 门禁：令牌必须可签发、可校验、会过期、认签发者，且不再接受任何固定开发串。
 *
 * <p>为什么单独测这一层：{@code AuthInterceptor} 只做「有 Bearer 就拿去 verify」， 真正的安全边界全在 {@link
 * TokenService}。这里把边界逐条钉死，控制器测试只需验证接线。
 */
class TokenServiceTest {

    private static final String SECRET = "0123456789abcdef0123456789abcdef";

    private static XiaoyiProperties.Auth auth(String secret, String issuer, long ttl) {
        XiaoyiProperties.Auth auth = new XiaoyiProperties.Auth();
        auth.setJwtSecret(secret);
        auth.setIssuer(issuer);
        auth.setTokenTtlSeconds(ttl);
        return auth;
    }

    private static TokenService service(String secret, String issuer, long ttl) {
        XiaoyiProperties properties = new XiaoyiProperties();
        properties.setAuth(auth(secret, issuer, ttl));
        return new TokenService(properties);
    }

    @Test
    void issuedTokenVerifiesBackToTheSameUser() {
        TokenService tokens = service(SECRET, "xiaoyi-rag", 3600);

        String token = tokens.issue(42L);

        assertThat(tokens.verify(token)).isEqualTo(42L);
    }

    @Test
    void tokenSignedWithAnotherSecretIsRejected() {
        TokenService issuer = service(SECRET, "xiaoyi-rag", 3600);
        TokenService verifier = service("ffffffffffffffffffffffffffffffff", "xiaoyi-rag", 3600);

        assertThat(verifier.verify(issuer.issue(42L))).isNull();
    }

    @Test
    void tokenFromAnotherIssuerIsRejected() {
        TokenService issuer = service(SECRET, "someone-else", 3600);
        TokenService verifier = service(SECRET, "xiaoyi-rag", 3600);

        assertThat(verifier.verify(issuer.issue(42L))).isNull();
    }

    @Test
    void expiredTokenIsRejected() {
        TokenService tokens = service(SECRET, "xiaoyi-rag", 3600);
        Instant past = Instant.now().minusSeconds(7200);
        String expired =
                JWT.create()
                        .withIssuer("xiaoyi-rag")
                        .withSubject("42")
                        .withIssuedAt(past)
                        .withExpiresAt(past.plusSeconds(60))
                        .sign(Algorithm.HMAC256(SECRET));

        assertThat(tokens.verify(expired)).isNull();
    }

    @Test
    void tokenWithoutExpiryClaimIsRejected() {
        TokenService tokens = service(SECRET, "xiaoyi-rag", 3600);
        String noExpiry =
                JWT.create()
                        .withIssuer("xiaoyi-rag")
                        .withSubject("42")
                        .withIssuedAt(Instant.now())
                        .sign(Algorithm.HMAC256(SECRET));

        assertThat(tokens.verify(noExpiry)).isNull();
    }

    @Test
    void tamperedPayloadIsRejected() {
        TokenService tokens = service(SECRET, "xiaoyi-rag", 3600);
        String token = tokens.issue(42L);
        String[] parts = token.split("\\.");
        // 把 subject 改成 7 但保留原签名：签名校验必须失败。
        String forgedPayload =
                java.util.Base64.getUrlEncoder()
                        .withoutPadding()
                        .encodeToString(
                                "{\"iss\":\"xiaoyi-rag\",\"sub\":\"7\"}"
                                        .getBytes(StandardCharsets.UTF_8));

        assertThat(tokens.verify(parts[0] + "." + forgedPayload + "." + parts[2])).isNull();
    }

    @Test
    void legacyDevelopmentTokenIsRejected() {
        TokenService tokens = service(SECRET, "xiaoyi-rag", 3600);

        assertThat(tokens.verify("dev-token")).isNull();
        assertThat(tokens.verify("demo-1")).isNull();
        assertThat(tokens.verify("")).isNull();
        assertThat(tokens.verify(null)).isNull();
    }

    @Test
    void blankSubjectOrNonPositiveIdIsRejected() {
        TokenService tokens = service(SECRET, "xiaoyi-rag", 3600);
        String zero =
                JWT.create()
                        .withIssuer("xiaoyi-rag")
                        .withSubject("0")
                        .withExpiresAt(Instant.now().plusSeconds(60))
                        .sign(Algorithm.HMAC256(SECRET));

        assertThat(tokens.verify(zero)).isNull();
    }

    @Test
    void shortSecretFailsFast() {
        assertThatThrownBy(() -> service("too-short", "xiaoyi-rag", 3600))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("AUTH_JWT_SECRET");
    }

    @Test
    void blankSecretFailsFast() {
        assertThatThrownBy(() -> service("   ", "xiaoyi-rag", 3600))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("AUTH_JWT_SECRET");
    }

    @Test
    void nonPositiveTtlFailsFast() {
        assertThatThrownBy(() -> service(SECRET, "xiaoyi-rag", 0))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("TTL");
    }

    @Test
    void issueRejectsNonPositiveUser() {
        TokenService tokens = service(SECRET, "xiaoyi-rag", 3600);

        assertThatThrownBy(() -> tokens.issue(0L)).isInstanceOf(IllegalArgumentException.class);
    }
}
