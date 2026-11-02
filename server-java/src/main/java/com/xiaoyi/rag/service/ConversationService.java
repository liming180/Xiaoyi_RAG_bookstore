package com.xiaoyi.rag.service;

import com.xiaoyi.rag.model.dto.CreateConversationRequest;
import com.xiaoyi.rag.model.vo.ConversationVO;
import com.xiaoyi.rag.model.vo.MessageVO;
import java.util.List;

/**
 * 会话与消息的业务接口（J2 的 5 条对外接口）。
 *
 * <p>全部软删：{@code deleted=true} 的行对上层不可见，不做物理删除。
 */
public interface ConversationService {

    /**
     * 会话列表，按 {@code updatedAt} 倒序。
     *
     * @param userId 当前用户
     * @return 会话视图列表
     */
    List<ConversationVO> list(Long userId);

    /**
     * 新建会话。
     *
     * @param userId 当前用户
     * @param request 请求体，可为 null（标题回落「新会话」）
     * @return 新建的会话视图
     */
    ConversationVO create(Long userId, CreateConversationRequest request);

    /**
     * 删除会话（软删），同时把该会话下所有消息标记删除。
     *
     * @param userId 当前用户
     * @param conversationId 会话 id
     */
    void delete(Long userId, Long conversationId);

    /**
     * 消息列表，按 {@code createdAt} 升序。
     *
     * <p>分页参数在契约里是可选的扩展（契约 {@code GET /conversations/{id}/messages} 只声明了路径参数）， 新增可选 query 参数属向后兼容。
     *
     * @param userId 当前用户
     * @param conversationId 会话 id
     * @param limit 每页条数，1..200，缺省 50；越界抛 40001
     * @param before 只取 {@code createdAt < before} 的更早消息，可为 null
     * @return 消息视图列表
     */
    List<MessageVO> listMessages(Long userId, Long conversationId, Integer limit, Long before);

    /**
     * F10 清空：删该会话下的消息，但保留会话本身。
     *
     * @param userId 当前用户
     * @param conversationId 会话 id
     */
    void clearMessages(Long userId, Long conversationId);
}
