package com.xiaoyi.rag.controller;

import com.xiaoyi.rag.common.interceptor.AuthInterceptor;
import com.xiaoyi.rag.common.result.Result;
import com.xiaoyi.rag.model.dto.CreateConversationRequest;
import com.xiaoyi.rag.model.vo.ConversationVO;
import com.xiaoyi.rag.model.vo.MessageVO;
import com.xiaoyi.rag.service.ConversationService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.util.List;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 会话与消息：5 条对外接口（J2 起全部真落库）。
 *
 * <p>operationId：listConversations / createConversation / deleteConversation / listMessages /
 * clearMessages。
 *
 * <p>返回类型直接是契约 VO（{@code List<ConversationVO>}），不再包 {@code Object}：Entity 不出 Controller，
 * 出参就是契约形状，编译期就能挡住字段漂移。
 */
@RestController
@RequestMapping("/api/v1/conversations")
@Tag(name = "会话")
public class ConversationController {

    private final ConversationService conversationService;

    public ConversationController(ConversationService conversationService) {
        this.conversationService = conversationService;
    }

    @GetMapping
    @Operation(operationId = "listConversations", summary = "会话列表（updatedAt 倒序）")
    public Result<List<ConversationVO>> list(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId) {
        return Result.ok(conversationService.list(currentUser(userId)));
    }

    @PostMapping
    @Operation(operationId = "createConversation", summary = "新建会话")
    public Result<ConversationVO> create(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId,
            @RequestBody(required = false) CreateConversationRequest request) {
        return Result.ok(conversationService.create(currentUser(userId), request));
    }

    @DeleteMapping("/{id}")
    @Operation(operationId = "deleteConversation", summary = "删除会话（含消息）")
    public Result<Void> delete(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId,
            @PathVariable String id) {
        conversationService.delete(currentUser(userId), parseId(id));
        return Result.ok();
    }

    /** limit / before 是契约之外的可选扩展，缺省时行为与契约完全一致。 */
    @GetMapping("/{id}/messages")
    @Operation(operationId = "listMessages", summary = "消息列表（createdAt 升序）")
    public Result<List<MessageVO>> messages(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId,
            @PathVariable String id,
            @RequestParam(required = false) Integer limit,
            @RequestParam(required = false) Long before) {
        return Result.ok(
                conversationService.listMessages(currentUser(userId), parseId(id), limit, before));
    }

    @DeleteMapping("/{id}/messages")
    @Operation(operationId = "clearMessages", summary = "清空消息但保留会话")
    public Result<Void> clearMessages(
            @RequestAttribute(name = AuthInterceptor.ATTR_USER_ID, required = false) Long userId,
            @PathVariable String id) {
        conversationService.clearMessages(currentUser(userId), parseId(id));
        return Result.ok();
    }

    /**
     * 取当前用户：拦截器已保证受保护路径带 token，这里只是兜底。
     *
     * @param userId 拦截器写入的请求属性
     * @return 非空用户 id
     */
    private Long currentUser(Long userId) {
        return userId == null ? 1L : userId;
    }

    /**
     * 路径 id 转 {@code Long}。契约里 id 是双形状，非数字一律当「不存在」， 交给 Service 抛 40406，避免变成 500。
     *
     * @param raw 路径上的 id
     * @return 解析后的 id；无法解析时返回 {@code -1}（任何真实 id 都不等于它）
     */
    private Long parseId(String raw) {
        try {
            return Long.valueOf(raw);
        } catch (NumberFormatException ex) {
            return -1L;
        }
    }
}
