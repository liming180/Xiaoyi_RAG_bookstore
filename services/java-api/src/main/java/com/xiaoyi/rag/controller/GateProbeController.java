package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;
import io.swagger.v3.oas.annotations.Hidden;
import org.springframework.context.annotation.Profile;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 门禁探针：只用于验证「错误码 → HTTP 状态码」映射，正常运行时不会加载。
 *
 * <p>背景：手册 §5 的 J1 测试要求「造 400（参数校验）、401（无 token）、409、503 四类」， 但 J1 骨架里没有任何真实业务能产生 409 /
 * 503（实验并发、建库任务并发、AI 不可用 都要等 J4 / J6）。所以提供一个只在 {@code gate-probe} profile 下注册的抛码端点， 让黑盒测试能真的走一遍
 * {@code GlobalExceptionHandler} 的 409 / 503 分支， 而不是靠读源码断言。
 *
 * <p>启用方式：{@code java -jar app.jar --spring.profiles.active=gate-probe}。 生产 /
 * 常规开发不激活，因此不会出现在对外路由表里。
 */
@Hidden
@RestController
@Profile("gate-probe")
public class GateProbeController {

    /**
     * 抛出指定错误码，由 {@code GlobalExceptionHandler} 转成信封。
     *
     * @param code 错误码，必须在 {@link ErrorCode} 里存在
     */
    @GetMapping("/__gate/throw")
    public void throwCode(@RequestParam("code") int code) {
        ErrorCode matched =
                java.util.Arrays.stream(ErrorCode.values())
                        .filter(item -> item.getCode() == code)
                        .findFirst()
                        .orElseThrow(
                                () ->
                                        new ApiException(
                                                ErrorCode.INVALID_PARAM.getCode(),
                                                "未登记的错误码 " + code));
        throw new ApiException(matched.getCode(), matched.getDefaultMessage());
    }
}
