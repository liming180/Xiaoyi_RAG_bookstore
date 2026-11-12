package com.xiaoyi.rag.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.xiaoyi.rag.client.AiServiceClient;
import com.xiaoyi.rag.client.dto.AiChatRequest;
import com.xiaoyi.rag.client.dto.AiStreamEvent;
import com.xiaoyi.rag.model.vo.EvalQuestionVO;
import com.xiaoyi.rag.repository.EvalRunRepository;
import com.xiaoyi.rag.service.impl.EvalServiceImpl;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;

/**
 * N1：实验参数必须以内部契约的 snake_case 形式进 `options`。
 *
 * <p>修这个缺陷之前，`EvalServiceImpl` 把整份实验参数（`chunkSize` / `k` 这些 camelCase 键） 原样塞进
 * `AiChatRequest.options`。内部契约 `InternalChatRequest` 没有声明 `options`， 即便声明了，Python 侧也只认 `rerank` /
 * `summary` / `chunk_size` / `overlap` 四个键 —— 其余键不报错、被静默忽略。于是「rerank=true / false 两组」跑出来一模一样。
 */
class EvalServiceOptionsTest {

    private final List<AiChatRequest> requests = new CopyOnWriteArrayList<>();

    private EvalServiceImpl service() {
        AiServiceClient ai = mock(AiServiceClient.class);
        doAnswer(
                        call -> {
                            AiChatRequest request = call.getArgument(1);
                            requests.add(request);
                            AiServiceClient.StreamListener listener = call.getArgument(2);
                            listener.onEvent(AiStreamEvent.token("答案"));
                            listener.onEvent(
                                    AiStreamEvent.done(
                                            "py-1",
                                            Map.of("promptTokens", 1),
                                            5L,
                                            false,
                                            List.of("追问"),
                                            null,
                                            null));
                            return AiServiceClient.StreamHandle.NOOP;
                        })
                .when(ai)
                .chatStream(anyLong(), any(), any());
        return new EvalServiceImpl(
                ai,
                mock(EvalRunRepository.class),
                new ObjectMapper(),
                mock(QuestionBankService.class));
    }

    @Test
    void camelCaseExperimentParamsBecomeSnakeCaseOptions() {
        EvalServiceImpl service = service();
        service.evaluate(
                7L,
                List.of(new EvalQuestionVO("T01", "fact", "问题", "关键词", "asset")),
                3,
                Map.of(
                        "chunkSize", 300,
                        "overlap", 50,
                        "k", 3,
                        "rerank", false,
                        "summary", true));

        // 每道题跑 direct + rag 两次。
        assertThat(requests).hasSize(2);
        Map<String, Object> options = requests.get(0).options();
        assertThat(options).containsEntry("rerank", false);
        assertThat(options).containsEntry("summary", true);
        assertThat(options).containsEntry("chunk_size", 300);
        assertThat(options).containsEntry("overlap", 50);
        // camelCase 键不许漏出去：Python 侧不认，漏出去只会被静默忽略。
        assertThat(options).doesNotContainKeys("chunkSize", "k");
    }

    @Test
    void plainEvalSendsEmptyOptions() {
        EvalServiceImpl service = service();
        service.evaluate(
                7L, List.of(new EvalQuestionVO("T01", "fact", "问题", "关键词", "asset")), 3, Map.of());

        assertThat(requests).hasSize(2);
        assertThat(requests.get(0).options()).isEmpty();
    }

    @Test
    void optionsAreNonNullForEveryRequest() {
        // AiChatRequest 的 options 用 @JsonInclude(NON_EMPTY)：null 会让字段消失，
        // Python 侧拿到的是缺省值，行为上等价但日志里看不出「这轮是实验通道」。
        EvalServiceImpl service = service();
        service.evaluate(
                7L,
                List.of(new EvalQuestionVO("T01", "fact", "问题", "关键词", "asset")),
                3,
                Map.of("rerank", true));
        AtomicReference<AiChatRequest> seen = new AtomicReference<>();
        requests.forEach(seen::set);
        assertThat(seen.get().options()).isNotNull();
        assertThat(seen.get().options()).containsEntry("rerank", true);
    }
}
