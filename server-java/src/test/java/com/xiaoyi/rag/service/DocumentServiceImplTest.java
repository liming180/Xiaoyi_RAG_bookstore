package com.xiaoyi.rag.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.model.dto.UpdateDocumentRequest;
import com.xiaoyi.rag.model.entity.Document;
import com.xiaoyi.rag.model.entity.IndexTask;
import com.xiaoyi.rag.model.vo.DocumentVO;
import com.xiaoyi.rag.model.vo.UploadResultVO;
import com.xiaoyi.rag.repository.DocumentRepository;
import com.xiaoyi.rag.repository.IndexTaskRepository;
import com.xiaoyi.rag.service.impl.DocumentServiceImpl;
import java.io.IOException;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.mock.web.MockMultipartFile;

/**
 * H2 资料隔离门禁：列表 / 改 / 删 / 去重 / 建库标脏全部按归属人收口。
 *
 * <p>这些断言对应施工单 H2 的验收：A 上传后 B 的列表读不到、B 改删 404、同一份正文被两人上传各存一份、 A 的删除不会中止 B 的建库任务。
 */
@ExtendWith(MockitoExtension.class)
class DocumentServiceImplTest {

    private static final Long OWNER = 5L;

    private static final Long OTHER = 9L;

    @Mock private DocumentRepository documents;

    @Mock private IndexTaskRepository tasks;

    @Mock private Storage storage;

    private DocumentServiceImpl service;

    @BeforeEach
    void setUp() {
        service = new DocumentServiceImpl(documents, tasks, storage);
    }

    @Test
    @DisplayName("列表只查本人的资料")
    void listIsOwnerScoped() {
        when(documents.findByUploadedByAndDeletedFalseOrderByUpdatedAtDescIdDesc(OTHER))
                .thenReturn(List.of());

        assertThat(service.list(OTHER)).isEmpty();

        verify(documents, never()).findByUploadedByAndDeletedFalseOrderByUpdatedAtDescIdDesc(OWNER);
    }

    @Test
    @DisplayName("同一份正文被两人上传：各自落一份，去重只在本人范围内生效")
    void dedupeIsScopedPerOwner() throws IOException {
        MockMultipartFile file =
                new MockMultipartFile("files", "note.md", "text/markdown", "# 标题\n正文".getBytes());
        when(documents.findFirstBySha256AndUploadedByAndDeletedFalse(any(), eq(OTHER)))
                .thenReturn(Optional.empty());
        when(documents.save(any())).thenAnswer(inv -> withId(inv.getArgument(0), 42L));
        when(storage.store(eq(42L), eq("note.md"), any())).thenReturn("42/note.md");

        UploadResultVO result = service.upload(List.of(file), OTHER);

        assertThat(result.accepted()).hasSize(1);
        assertThat(result.accepted().get(0).id()).isEqualTo("42");
        ArgumentCaptor<Document> saved = ArgumentCaptor.forClass(Document.class);
        verify(documents, org.mockito.Mockito.atLeastOnce()).save(saved.capture());
        assertThat(saved.getValue().getUploadedBy()).isEqualTo(OTHER);
        verify(documents).markIndexedAsNeedsRebuild(OTHER);
    }

    @Test
    @DisplayName("本人已传过同一份内容：直接回已有记录，不重复落盘")
    void duplicateWithinOwnerReturnsExistingRow() throws Exception {
        MockMultipartFile file =
                new MockMultipartFile("files", "note.md", "text/markdown", "# 标题\n正文".getBytes());
        Document existing = document(7L, OWNER);
        when(documents.findFirstBySha256AndUploadedByAndDeletedFalse(any(), eq(OWNER)))
                .thenReturn(Optional.of(existing));

        UploadResultVO result = service.upload(List.of(file), OWNER);

        assertThat(result.accepted()).hasSize(1);
        assertThat(result.accepted().get(0).id()).isEqualTo("7");
        verify(storage, never()).store(anyLong(), any(), any());
    }

    @Test
    @DisplayName("改别人的资料：等同不存在（40401），且不写库")
    void updateOfAnotherUsersDocumentIsNotFound() {
        when(documents.findByIdAndUploadedByAndDeletedFalse(7L, OTHER))
                .thenReturn(Optional.empty());

        assertThatThrownBy(
                        () ->
                                service.update(
                                        OTHER,
                                        7L,
                                        new UpdateDocumentRequest("新标题", null, null, null)))
                .isInstanceOf(ApiException.class)
                .extracting(ex -> ((ApiException) ex).getCode())
                .isEqualTo(ErrorCode.DOCUMENT_NOT_FOUND.getCode());

        verify(documents, never()).save(any());
    }

    @Test
    @DisplayName("改自己的资料：标题落库并把本人索引标脏")
    void updateOfOwnDocumentMarksNeedsRebuild() {
        Document entity = document(7L, OWNER);
        when(documents.findByIdAndUploadedByAndDeletedFalse(7L, OWNER))
                .thenReturn(Optional.of(entity));
        when(documents.save(any())).thenAnswer(inv -> inv.getArgument(0));

        DocumentVO vo =
                service.update(OWNER, 7L, new UpdateDocumentRequest("新标题", null, null, null));

        assertThat(vo.title()).isEqualTo("新标题");
        verify(documents).markIndexedAsNeedsRebuild(OWNER);
    }

    @Test
    @DisplayName("删别人的资料：40401，且不动任务、不删盘、不软删")
    void deleteOfAnotherUsersDocumentIsNotFound() {
        when(documents.findByIdAndUploadedByAndDeletedFalse(7L, OTHER))
                .thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.delete(OTHER, 7L))
                .isInstanceOf(ApiException.class)
                .extracting(ex -> ((ApiException) ex).getCode())
                .isEqualTo(ErrorCode.DOCUMENT_NOT_FOUND.getCode());

        verify(tasks, never()).findByUserIdAndStatusInOrderByCreatedAtDesc(anyLong(), any());
        verify(documents, never()).softDeleteByIdAndUploadedBy(anyLong(), anyLong());
    }

    @Test
    @DisplayName("删自己的资料：只中止本人未完成任务，只软删本人行")
    void deleteStopsOnlyOwnTasks() throws IOException {
        Document entity = document(7L, OWNER);
        IndexTask running = new IndexTask();
        running.setId(3L);
        running.setUserId(OWNER);
        running.setStatus(IndexTask.STATUS_RUNNING);
        when(documents.findByIdAndUploadedByAndDeletedFalse(7L, OWNER))
                .thenReturn(Optional.of(entity));
        when(tasks.findByUserIdAndStatusInOrderByCreatedAtDesc(eq(OWNER), any()))
                .thenReturn(List.of(running));
        when(storage.deleteByDocumentId(7L)).thenReturn(true);

        service.delete(OWNER, 7L);

        assertThat(running.getStatus()).isEqualTo(IndexTask.STATUS_FAILED);
        assertThat(running.getError()).contains("资料已删除");
        verify(tasks, never()).findByUserIdAndStatusInOrderByCreatedAtDesc(eq(OTHER), any());
        verify(documents).softDeleteByIdAndUploadedBy(7L, OWNER);
        verify(documents).markIndexedAsNeedsRebuild(OWNER);
    }

    /* ------------------------------------------------------------ 构造 */

    private static Document withId(Document document, Long id) {
        document.setId(id);
        return document;
    }

    private static Document document(Long id, Long owner) {
        Document doc = new Document();
        doc.setId(id);
        doc.setUploadedBy(owner);
        doc.setFilename("note.md");
        doc.setTitle("标题");
        doc.setVersion("v1");
        doc.setStatus("UPLOADING");
        doc.setCharCount(6);
        doc.setChunkCount(0);
        doc.setVerified(true);
        doc.setTags("");
        doc.setUpdatedAt(1_700_000_000L);
        return doc;
    }
}
