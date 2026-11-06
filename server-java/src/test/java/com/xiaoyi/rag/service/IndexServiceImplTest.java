package com.xiaoyi.rag.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.xiaoyi.rag.client.AiServiceClient;
import com.xiaoyi.rag.client.dto.AiChunk;
import com.xiaoyi.rag.client.dto.AiIngestTask;
import com.xiaoyi.rag.client.dto.AiParseRequest;
import com.xiaoyi.rag.client.dto.AiParseResult;
import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.config.XiaoyiProperties;
import com.xiaoyi.rag.model.dto.RebuildRequest;
import com.xiaoyi.rag.model.entity.Chunk;
import com.xiaoyi.rag.model.entity.Document;
import com.xiaoyi.rag.model.entity.IndexTask;
import com.xiaoyi.rag.model.vo.IndexTaskVO;
import com.xiaoyi.rag.repository.ChunkRepository;
import com.xiaoyi.rag.repository.DocumentRepository;
import com.xiaoyi.rag.repository.IndexTaskRepository;
import com.xiaoyi.rag.service.impl.IndexServiceImpl;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DataIntegrityViolationException;

/**
 * H3 任务一致性门禁：串行受理、幂等重试、快照判据、失败不破坏上一代。
 *
 * <p>这些断言对应施工单 H3 的四条验收：并发重建只受理一个、超时重试复用同一任务、重启后有确定终态、 失败不破坏上一代索引。全部走真实 Service，仓储与 AI 客户端是 mock ——
 * 只验编排逻辑，不依赖 MySQL 与 Python。
 */
@ExtendWith(MockitoExtension.class)
class IndexServiceImplTest {

    private static final Long OWNER = 11L;

    private static final Long OTHER = 22L;

    @Mock private IndexTaskRepository tasks;

    @Mock private DocumentRepository documents;

    @Mock private ChunkRepository chunks;

    @Mock private AiServiceClient ai;

    @Mock private Storage storage;

    private IndexServiceImpl service;

    @BeforeEach
    void setUp() {
        XiaoyiProperties properties = new XiaoyiProperties();
        properties.getIndex().setDefaultChunkSize(180);
        properties.getIndex().setDefaultOverlap(30);
        properties.getIndex().setEmbeddingModel("mock-embedding");
        service =
                new IndexServiceImpl(
                        tasks, documents, chunks, ai, storage, properties, new ObjectMapper());
    }

    /* ------------------------------------------------------------ 受理 */

    @Test
    @DisplayName("已有未终态任务时第二次重建返回 40903，且不创建新任务")
    void rebuildRejectsWhenAnActiveTaskAlreadyExists() {
        when(tasks.findByUserIdAndStatusInOrderByCreatedAtDesc(eq(OWNER), any()))
                .thenReturn(List.of(task(1L, OWNER, IndexTask.STATUS_RUNNING)));

        assertThatThrownBy(() -> service.rebuild(OWNER, new RebuildRequest(180, 30)))
                .isInstanceOf(ApiException.class)
                .extracting(ex -> ((ApiException) ex).getCode())
                .isEqualTo(ErrorCode.INDEX_TASK_ALREADY_RUNNING.getCode());

        verify(tasks, never()).saveAndFlush(any());
        verify(ai, never()).parseDocuments(anyLong(), any());
    }

    @Test
    @DisplayName("预检查通过但库层唯一键冲突时同样翻译成 40903")
    void rebuildTranslatesUniqueKeyRaceIntoConflict() {
        when(tasks.findByUserIdAndStatusInOrderByCreatedAtDesc(eq(OWNER), any()))
                .thenReturn(List.of());
        when(documents.findByUploadedByAndDeletedFalseAndStatusNot(OWNER, "DISABLED"))
                .thenReturn(List.of());
        when(tasks.saveAndFlush(any()))
                .thenThrow(new DataIntegrityViolationException("uk_index_task_active_user"));

        assertThatThrownBy(() -> service.rebuild(OWNER, new RebuildRequest(180, 30)))
                .isInstanceOf(ApiException.class)
                .extracting(ex -> ((ApiException) ex).getCode())
                .isEqualTo(ErrorCode.INDEX_TASK_ALREADY_RUNNING.getCode());
    }

    @Test
    @DisplayName("空语料重建直接收成 SUCCEEDED 并清空本人旧片段，不把空列表发给 Python")
    void rebuildWithEmptyCorpusFinishesWithoutCallingPython() {
        when(tasks.findByUserIdAndStatusInOrderByCreatedAtDesc(eq(OWNER), any()))
                .thenReturn(List.of());
        when(documents.findByUploadedByAndDeletedFalseAndStatusNot(OWNER, "DISABLED"))
                .thenReturn(List.of());
        when(tasks.saveAndFlush(any())).thenAnswer(inv -> withId(inv.getArgument(0), 101L));

        IndexTaskVO vo = service.rebuild(OWNER, new RebuildRequest(50, 49));

        assertThat(vo.status()).isEqualTo(IndexTask.STATUS_SUCCEEDED);
        assertThat(vo.stage()).isEqualTo(IndexTask.STAGE_DONE);
        assertThat(vo.progress()).isEqualTo(100);
        assertThat(vo.chunkSize()).isEqualTo(50);
        assertThat(vo.finishedAt()).isNotNull();
        // ParseRequest.documents 有 minItems 1，空列表硬送会被 Python 判 400 再翻成 50301。
        verify(ai, never()).parseDocuments(anyLong(), any());
        // 空索引仍要清掉本人上一代片段，否则 /chunks 会残留已删除资料的内容。
        verify(chunks).deleteByUserIdAndTaskIdNot(OWNER, 101L);
    }

    @Test
    @DisplayName("A 的重建只看到 A 的资料：跨用户资料不会进快照")
    void rebuildOnlySnapshotsOwnDocuments() throws Exception {
        when(tasks.findByUserIdAndStatusInOrderByCreatedAtDesc(eq(OWNER), any()))
                .thenReturn(List.of());
        when(documents.findByUploadedByAndDeletedFalseAndStatusNot(OWNER, "DISABLED"))
                .thenReturn(List.of(document(7L, OWNER, 3L)));
        when(storage.read("7/note.md"))
                .thenReturn(new ByteArrayInputStream("正文".getBytes(StandardCharsets.UTF_8)));
        when(tasks.saveAndFlush(any())).thenAnswer(inv -> withId(inv.getArgument(0), 100L));
        when(ai.parseDocuments(eq(OWNER), any())).thenReturn(new AiParseResult("py-task-1", 1));

        IndexTaskVO vo = service.rebuild(OWNER, new RebuildRequest(180, 30));

        assertThat(vo.id()).isEqualTo("100");
        ArgumentCaptor<AiParseRequest> captor = ArgumentCaptor.forClass(AiParseRequest.class);
        verify(ai).parseDocuments(eq(OWNER), captor.capture());
        assertThat(captor.getValue().documents()).hasSize(1);
        assertThat(captor.getValue().documents().get(0).docId()).isEqualTo("7");
        assertThat(captor.getValue().submissionKey()).isNotBlank();
        assertThat(captor.getValue().generation()).isNotBlank();
    }

    @Test
    @DisplayName("触发失败：任务置 FAILED 并抛 50301，不留永远 PENDING 的任务")
    void rebuildMarksTaskFailedWhenTriggerFails() throws Exception {
        when(tasks.findByUserIdAndStatusInOrderByCreatedAtDesc(eq(OWNER), any()))
                .thenReturn(List.of());
        when(documents.findByUploadedByAndDeletedFalseAndStatusNot(OWNER, "DISABLED"))
                .thenReturn(List.of(document(7L, OWNER, 1L)));
        when(storage.read("7/note.md"))
                .thenReturn(new ByteArrayInputStream("正文".getBytes(StandardCharsets.UTF_8)));
        when(tasks.saveAndFlush(any())).thenAnswer(inv -> withId(inv.getArgument(0), 100L));
        when(ai.parseDocuments(eq(OWNER), any())).thenThrow(new IllegalStateException("python 挂了"));

        assertThatThrownBy(() -> service.rebuild(OWNER, new RebuildRequest(180, 30)))
                .isInstanceOf(ApiException.class)
                .extracting(ex -> ((ApiException) ex).getCode())
                .isEqualTo(ErrorCode.AI_UNAVAILABLE.getCode());

        ArgumentCaptor<IndexTask> saved = ArgumentCaptor.forClass(IndexTask.class);
        verify(tasks).save(saved.capture());
        assertThat(saved.getValue().getStatus()).isEqualTo(IndexTask.STATUS_FAILED);
        assertThat(saved.getValue().getFinishedAt()).isNotNull();
    }

    /* ------------------------------------------------------------ 幂等 */

    @Test
    @DisplayName("轮询补触发复用任务自身的 submission_key，不重新生成")
    void retriggerReusesTheStoredSubmissionKey() throws Exception {
        IndexTask stuck = task(5L, OWNER, IndexTask.STATUS_PENDING);
        stuck.setSubmissionKey("stored-key");
        stuck.setGeneration("stored-generation");
        stuck.setChunkSize(180);
        stuck.setOverlap(30);
        stuck.setSnapshotJson("[{\"id\":7,\"revision\":4}]");
        when(tasks.findByStatusInOrderByCreatedAtAsc(any())).thenReturn(List.of(stuck));
        when(documents.findByIdAndUploadedByAndDeletedFalse(7L, OWNER))
                .thenReturn(Optional.of(document(7L, OWNER, 4L)));
        when(storage.read("7/note.md"))
                .thenReturn(new ByteArrayInputStream("正文".getBytes(StandardCharsets.UTF_8)));
        when(ai.parseDocuments(eq(OWNER), any())).thenReturn(new AiParseResult("py-task-9", 1));

        service.pollOnce();

        ArgumentCaptor<AiParseRequest> captor = ArgumentCaptor.forClass(AiParseRequest.class);
        verify(ai).parseDocuments(eq(OWNER), captor.capture());
        assertThat(captor.getValue().submissionKey()).isEqualTo("stored-key");
        assertThat(captor.getValue().generation()).isEqualTo("stored-generation");
        assertThat(stuck.getExternalTaskId()).isEqualTo("py-task-9");
        assertThat(stuck.getStatus()).isEqualTo(IndexTask.STATUS_RUNNING);
    }

    @Test
    @DisplayName("补触发只带快照里的资料：建库期间新上传的资料不进这一代")
    void retriggerUsesSnapshotNotCurrentDocumentSet() throws Exception {
        IndexTask stuck = task(6L, OWNER, IndexTask.STATUS_PENDING);
        stuck.setSnapshotJson("[{\"id\":7,\"revision\":1}]");
        when(tasks.findByStatusInOrderByCreatedAtAsc(any())).thenReturn(List.of(stuck));
        when(documents.findByIdAndUploadedByAndDeletedFalse(7L, OWNER))
                .thenReturn(Optional.of(document(7L, OWNER, 1L)));
        when(storage.read("7/note.md"))
                .thenReturn(new ByteArrayInputStream("正文".getBytes(StandardCharsets.UTF_8)));
        when(ai.parseDocuments(eq(OWNER), any())).thenReturn(new AiParseResult("py-task-10", 1));

        service.pollOnce();

        verify(documents, never()).findByUploadedByAndDeletedFalseAndStatusNot(anyLong(), any());
        ArgumentCaptor<AiParseRequest> captor = ArgumentCaptor.forClass(AiParseRequest.class);
        verify(ai).parseDocuments(eq(OWNER), captor.capture());
        assertThat(captor.getValue().documents()).hasSize(1);
    }

    /* ------------------------------------------------------------ 收尾 */

    @Test
    @DisplayName("建库期间被改过的资料影响 0 行，保留待建状态且不报错")
    void promoteSkipsDocumentsChangedAfterSnapshot() {
        IndexTask task = task(9L, OWNER, IndexTask.STATUS_RUNNING);
        task.setExternalTaskId("py-task-2");
        task.setSnapshotJson("[{\"id\":7,\"revision\":4},{\"id\":8,\"revision\":2}]");
        when(tasks.findByStatusInOrderByCreatedAtAsc(any())).thenReturn(List.of(task));
        when(ai.getIngestTask(OWNER, "py-task-2"))
                .thenReturn(
                        new AiIngestTask(
                                "py-task-2",
                                "SUCCEEDED",
                                "done",
                                100,
                                2,
                                2,
                                null,
                                List.of(chunk("7"), chunk("8"))));
        // 7 号在快照后被改动 → 0 行；8 号没动 → 1 行。
        when(documents.markSnapshotIndexed(eq(OWNER), eq(7L), eq(4L), anyInt(), anyLong()))
                .thenReturn(0);
        when(documents.markSnapshotIndexed(eq(OWNER), eq(8L), eq(2L), anyInt(), anyLong()))
                .thenReturn(1);

        service.pollOnce();

        assertThat(task.getStatus()).isEqualTo(IndexTask.STATUS_SUCCEEDED);
        assertThat(task.getStage()).isEqualTo(IndexTask.STAGE_DONE);
        assertThat(task.getProgress()).isEqualTo(100);
        verify(chunks).deleteByUserIdAndTaskIdNot(OWNER, 9L);
    }

    @Test
    @DisplayName("成功收尾按用户整代替换片段，删除条件带 user_id")
    void persistChunksOnlyReplacesOwnGeneration() {
        IndexTask task = task(9L, OWNER, IndexTask.STATUS_RUNNING);
        task.setExternalTaskId("py-task-2");
        task.setSnapshotJson("[]");
        when(tasks.findByStatusInOrderByCreatedAtAsc(any())).thenReturn(List.of(task));
        when(ai.getIngestTask(OWNER, "py-task-2"))
                .thenReturn(
                        new AiIngestTask(
                                "py-task-2",
                                "SUCCEEDED",
                                "done",
                                100,
                                1,
                                1,
                                null,
                                List.of(chunk("7"))));

        service.pollOnce();

        verify(chunks).deleteByUserIdAndTaskIdNot(OWNER, 9L);
        verify(chunks, never()).deleteByUserIdAndTaskIdNot(eq(OTHER), anyLong());
    }

    @Test
    @DisplayName("失败任务只标脏本人资料，不删上一代片段")
    void failedTaskKeepsPreviousGeneration() {
        IndexTask task = task(9L, OWNER, IndexTask.STATUS_RUNNING);
        task.setExternalTaskId("py-task-3");
        when(tasks.findByStatusInOrderByCreatedAtAsc(any())).thenReturn(List.of(task));
        when(ai.getIngestTask(OWNER, "py-task-3"))
                .thenReturn(
                        new AiIngestTask(
                                "py-task-3", "FAILED", "embedding", 45, 1, 0, "向量服务 500", null));

        service.pollOnce();

        assertThat(task.getStatus()).isEqualTo(IndexTask.STATUS_FAILED);
        assertThat(task.getError()).contains("向量服务 500");
        verify(documents).markFailedForOwner(OWNER, task.getError());
        verify(chunks, never()).deleteByUserIdAndTaskIdNot(anyLong(), anyLong());
    }

    @Test
    @DisplayName("轮询连续失败 30 次才判死，前 29 次保持 RUNNING")
    void pollFailuresAreCountedBeforeFailing() {
        IndexTask task = task(9L, OWNER, IndexTask.STATUS_RUNNING);
        task.setExternalTaskId("py-task-4");
        task.setPollFailures(IndexTask.MAX_POLL_FAILURES - 1);
        when(tasks.findByStatusInOrderByCreatedAtAsc(any())).thenReturn(List.of(task));
        when(ai.getIngestTask(OWNER, "py-task-4")).thenThrow(new IllegalStateException("超时"));

        service.pollOnce();

        assertThat(task.getStatus()).isEqualTo(IndexTask.STATUS_FAILED);
        assertThat(task.getError()).contains("轮询连续失败 30 次");
    }

    @Test
    @DisplayName("跨用户任务查不到：task() 回 40402 而不是别人的任务")
    void taskIsOwnerScoped() {
        when(tasks.findByIdAndUserId(9L, OTHER)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.task(OTHER, "9"))
                .isInstanceOf(ApiException.class)
                .extracting(ex -> ((ApiException) ex).getCode())
                .isEqualTo(ErrorCode.INDEX_TASK_NOT_FOUND.getCode());
    }

    @Test
    @DisplayName("片段浏览只读本人片段")
    void listChunksIsOwnerScoped() {
        when(chunks.findByUserIdOrderBySeqAscIdAsc(OTHER)).thenReturn(List.of());

        assertThat(service.listChunks(OTHER, null, null, null)).isEmpty();
        verify(chunks, never()).findByUserIdOrderBySeqAscIdAsc(OWNER);
    }

    /* ------------------------------------------------------------ 构造 */

    private static IndexTask task(Long id, Long userId, String status) {
        IndexTask task = new IndexTask();
        task.setId(id);
        task.setUserId(userId);
        task.setStatus(status);
        task.setStage(IndexTask.STAGE_PARSING);
        task.setProgress(0);
        task.setChunkSize(180);
        task.setOverlap(30);
        task.setDocCount(1);
        task.setChunkCount(0);
        task.setPollFailures(0);
        task.setCreatedAt(1_700_000_000L);
        return task;
    }

    private static IndexTask withId(IndexTask task, Long id) {
        task.setId(id);
        return task;
    }

    private static Document document(Long id, Long owner, Long revision) {
        Document doc = new Document();
        doc.setId(id);
        doc.setUploadedBy(owner);
        doc.setRevision(revision);
        doc.setFilename("note.md");
        doc.setTitle("笔记");
        doc.setStorageKey(id + "/note.md");
        doc.setVersion("v1");
        doc.setStatus("NEEDS_REBUILD");
        return doc;
    }

    private static AiChunk chunk(String docId) {
        return new AiChunk(
                "D" + docId + "-C001", docId, "笔记", "", "正文", 0, 2, Chunk.KIND_CHUNK, true);
    }
}
