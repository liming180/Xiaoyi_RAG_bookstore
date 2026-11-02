package com.xiaoyi.rag.service.impl;

import com.xiaoyi.rag.client.AiServiceClient;
import com.xiaoyi.rag.client.dto.AiChunk;
import com.xiaoyi.rag.client.dto.AiIndexManifest;
import com.xiaoyi.rag.client.dto.AiIngestTask;
import com.xiaoyi.rag.client.dto.AiParseDocumentItem;
import com.xiaoyi.rag.client.dto.AiParseRequest;
import com.xiaoyi.rag.client.dto.AiParseResult;
import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.config.XiaoyiProperties;
import com.xiaoyi.rag.model.dto.RebuildRequest;
import com.xiaoyi.rag.model.entity.Chunk;
import com.xiaoyi.rag.model.entity.Document;
import com.xiaoyi.rag.model.entity.IndexTask;
import com.xiaoyi.rag.model.vo.ChunkItemVO;
import com.xiaoyi.rag.model.vo.IndexManifestVO;
import com.xiaoyi.rag.model.vo.IndexStatusVO;
import com.xiaoyi.rag.model.vo.IndexTaskVO;
import com.xiaoyi.rag.repository.ChunkRepository;
import com.xiaoyi.rag.repository.DocumentRepository;
import com.xiaoyi.rag.repository.IndexTaskRepository;
import com.xiaoyi.rag.service.IndexService;
import com.xiaoyi.rag.service.Storage;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 建库编排实现。
 *
 * <p>三个关键决策：
 *
 * <ul>
 *   <li><b>触发 parse 放在 rebuild 里同步做，而不是丢给轮询器。</b> 契约 {@code /api/v1/index/rebuild} 的 {@code
 *       x-error-codes} 明确包含 {@code 50301}——如果触发只发生在后台轮询里，这条路由永远回不出 50301， 前端就无法在「点重建」的当下告诉用户 Python
 *       挂了。 轮询器里保留同一条触发路径，纯粹用于崩溃自愈（任务已落库但 externalTaskId 还没写上）。
 *   <li><b>片段缓存整表以最后一次成功建库为准。</b> 成功后先删掉旧任务的全部片段再写入，避免两代产物混在一起 —— 这正是 {@code /index/status} 的
 *       needs_rebuild 语义所依赖的「当前缓存 == 最近一次成功」不变量。
 *   <li><b>status 优先从本地库推导，Python 只用来判可用性。</b> docCount / chunkCount / 参数都取自本地，重启后仍准确； 若全部依赖
 *       Python， 它的任务表一丢，页面上的统计就归零了。
 * </ul>
 */
@Service
public class IndexServiceImpl implements IndexService {

    private static final Logger log = LoggerFactory.getLogger(IndexServiceImpl.class);

    /** 契约 ChunkKind 白名单。 */
    private static final Set<String> KINDS =
            new LinkedHashSet<>(List.of(Chunk.KIND_CHUNK, Chunk.KIND_SUMMARY, Chunk.KIND_RULE));

    /** 契约 IndexTaskStage 白名单，Python 原始 stage 必须先映射到这里。 */
    private static final Set<String> STAGES =
            new LinkedHashSet<>(
                    List.of(
                            IndexTask.STAGE_PARSING,
                            IndexTask.STAGE_SPLITTING,
                            IndexTask.STAGE_EMBEDDING,
                            IndexTask.STAGE_SUMMARIZING,
                            IndexTask.STAGE_DONE));

    /** 视为「尚未入库」的资料状态，出现任意一条就让 /index/status 变 needs_rebuild。 */
    private static final List<String> STALE_DOC_STATUS =
            List.of("UPLOADING", "PARSING", "FAILED", "NEEDS_REBUILD");

    private static final int MIN_CHUNK_SIZE = 50;

    private static final int MAX_CHUNK_SIZE = 1000;

    private static final String MSG_CHUNK_SIZE = "片段长度需在 50-1000 之间";

    private static final String MSG_OVERLAP = "重叠字数必须小于片段长度";

    private final IndexTaskRepository indexTaskRepository;

    private final DocumentRepository documentRepository;

    private final ChunkRepository chunkRepository;

    private final AiServiceClient aiClient;

    private final Storage storage;

    private final XiaoyiProperties properties;

    public IndexServiceImpl(
            IndexTaskRepository indexTaskRepository,
            DocumentRepository documentRepository,
            ChunkRepository chunkRepository,
            AiServiceClient aiClient,
            Storage storage,
            XiaoyiProperties properties) {
        this.indexTaskRepository = indexTaskRepository;
        this.documentRepository = documentRepository;
        this.chunkRepository = chunkRepository;
        this.aiClient = aiClient;
        this.storage = storage;
        this.properties = properties;
    }

    /* ------------------------------------------------------------ 状态 */

    @Override
    @Transactional(readOnly = true)
    public IndexStatusVO status() {
        List<Document> docs = documentRepository.findByDeletedFalseOrderByUpdatedAtDescIdDesc();
        Optional<IndexTask> lastOk =
                indexTaskRepository.findFirstByStatusOrderByFinishedAtDescIdDesc(
                        IndexTask.STATUS_SUCCEEDED);

        int chunkSize =
                lastOk.map(IndexTask::getChunkSize)
                        .orElse(properties.getIndex().getDefaultChunkSize());
        int overlap =
                lastOk.map(IndexTask::getOverlap).orElse(properties.getIndex().getDefaultOverlap());
        String embeddingModel =
                lastOk.map(IndexTask::getEmbeddingModel)
                        .filter(value -> value != null && !value.isBlank())
                        .orElse(properties.getIndex().getEmbeddingModel());
        Long lastBuiltAt = lastOk.map(IndexTask::getFinishedAt).orElse(null);
        int docCount = docs.size();
        int chunkCount = (int) chunkRepository.count();

        // Python 是否活着只影响 status 取值，不影响本次响应能否成功（unavailable 也是 HTTP 200）。
        AiIndexManifest manifest;
        try {
            manifest = aiClient.getIndexManifest();
        } catch (RuntimeException ex) {
            log.warn(
                    "查询 AI 索引状态失败，合成 unavailable：{} - {}",
                    ex.getClass().getSimpleName(),
                    ex.getMessage());
            return new IndexStatusVO(
                    "unavailable",
                    docCount,
                    chunkCount,
                    chunkSize,
                    overlap,
                    embeddingModel,
                    lastBuiltAt,
                    "AI 服务不可达",
                    manifestOf(lastOk.orElse(null)));
        }

        List<String> stale = new ArrayList<>();
        for (Document doc : docs) {
            if (STALE_DOC_STATUS.contains(doc.getStatus())) {
                stale.add(doc.getTitle() == null ? doc.getFilename() : doc.getTitle());
            }
        }
        if (!stale.isEmpty()) {
            return new IndexStatusVO(
                    "needs_rebuild",
                    docCount,
                    chunkCount,
                    chunkSize,
                    overlap,
                    embeddingModel,
                    lastBuiltAt,
                    stale.size() + " 份资料尚未入库",
                    manifestOf(lastOk.orElse(null)));
        }
        if (lastOk.isEmpty()) {
            return new IndexStatusVO(
                    "needs_rebuild",
                    docCount,
                    chunkCount,
                    chunkSize,
                    overlap,
                    embeddingModel,
                    lastBuiltAt,
                    "尚未建库",
                    null);
        }
        // Python 侧记的参数与最近成功任务不一致，说明缓存产物不是按当前参数生成的。
        if (manifest != null
                && manifest.chunkSize() != null
                && !manifest.chunkSize().equals(chunkSize)) {
            return new IndexStatusVO(
                    "needs_rebuild",
                    docCount,
                    chunkCount,
                    chunkSize,
                    overlap,
                    embeddingModel,
                    lastBuiltAt,
                    "建库参数已变更",
                    manifestOf(lastOk.get()));
        }
        return new IndexStatusVO(
                "ready",
                docCount,
                chunkCount,
                chunkSize,
                overlap,
                embeddingModel,
                lastBuiltAt,
                null,
                manifestOf(lastOk.get()));
    }

    /* ------------------------------------------------------------ 重建 */

    @Override
    @Transactional
    public IndexTaskVO rebuild(RebuildRequest request) {
        int chunkSize =
                request == null || request.chunkSize() == null
                        ? properties.getIndex().getDefaultChunkSize()
                        : request.chunkSize();
        int overlap =
                request == null || request.overlap() == null
                        ? properties.getIndex().getDefaultOverlap()
                        : request.overlap();
        validate(chunkSize, overlap);

        // 建库串行：已有在跑的任务就直接 409，别让两次重建互相覆盖片段缓存。
        List<IndexTask> running =
                indexTaskRepository.findByStatusInOrderByCreatedAtAsc(
                        List.of(IndexTask.STATUS_PENDING, IndexTask.STATUS_RUNNING));
        if (!running.isEmpty()) {
            throw new ApiException(
                    ErrorCode.INDEX_TASK_ALREADY_RUNNING.getCode(),
                    ErrorCode.INDEX_TASK_ALREADY_RUNNING.getDefaultMessage());
        }

        List<Document> docs = indexableDocuments();
        IndexTask task = new IndexTask();
        task.setStatus(IndexTask.STATUS_PENDING);
        task.setStage(IndexTask.STAGE_PARSING);
        task.setProgress(0);
        task.setChunkSize(chunkSize);
        task.setOverlap(overlap);
        task.setEmbeddingModel(properties.getIndex().getEmbeddingModel());
        task.setDocCount(docs.size());
        task.setChunkCount(0);
        task.setPollFailures(0);
        task.setCreatedAt(Instant.now().getEpochSecond());
        IndexTask saved = indexTaskRepository.save(task);

        triggerParse(saved, docs);
        return toTaskVO(saved);
    }

    /**
     * 调 Python 触发入库并把 external_task_id 写回任务。
     *
     * <p>失败时任务置 FAILED 并抛 {@code 50301}：重建这个动作在用户视角是「点一下」， 触发都失败就没必要留一个永远 PENDING 的任务让前端轮询到超时。
     *
     * @param task 任务实体（已落库，有 id）
     * @param docs 待入库资料
     */
    private void triggerParse(IndexTask task, List<Document> docs) {
        List<AiParseDocumentItem> items = new ArrayList<>(docs.size());
        for (Document doc : docs) {
            String text = readText(doc);
            if (text == null || text.isBlank()) {
                log.warn("资料 {} 正文读不出来，跳过入库", doc.getId());
                continue;
            }
            items.add(
                    new AiParseDocumentItem(
                            String.valueOf(doc.getId()),
                            doc.getFilename(),
                            doc.getTitle(),
                            text,
                            splitTags(doc.getTags()),
                            doc.getVersion()));
        }
        AiParseResult accepted;
        try {
            accepted =
                    aiClient.parseDocuments(
                            new AiParseRequest(items, task.getChunkSize(), task.getOverlap()));
        } catch (RuntimeException ex) {
            log.error("触发建库失败：{} - {}", ex.getClass().getSimpleName(), ex.getMessage());
            task.setStatus(IndexTask.STATUS_FAILED);
            task.setError(truncate(ex.getMessage()));
            task.setFinishedAt(Instant.now().getEpochSecond());
            indexTaskRepository.save(task);
            throw new ApiException(
                    ErrorCode.AI_UNAVAILABLE.getCode(),
                    ErrorCode.AI_UNAVAILABLE.getDefaultMessage());
        }
        task.setExternalTaskId(accepted.taskId());
        task.setStatus(IndexTask.STATUS_RUNNING);
        task.setStage(IndexTask.STAGE_PARSING);
        task.setDocCount(items.size());
        indexTaskRepository.save(task);
        log.info(
                "建库任务 {} 已触发，Python task_id={}，资料 {} 份",
                task.getId(),
                accepted.taskId(),
                items.size());
    }

    /* ------------------------------------------------------------ 任务 */

    @Override
    @Transactional(readOnly = true)
    public IndexTaskVO task(String id) {
        Long taskId = parseId(id);
        if (taskId == null) {
            throw new ApiException(
                    ErrorCode.INDEX_TASK_NOT_FOUND.getCode(),
                    ErrorCode.INDEX_TASK_NOT_FOUND.getDefaultMessage());
        }
        IndexTask entity =
                indexTaskRepository
                        .findById(taskId)
                        .orElseThrow(
                                () ->
                                        new ApiException(
                                                ErrorCode.INDEX_TASK_NOT_FOUND.getCode(),
                                                ErrorCode.INDEX_TASK_NOT_FOUND
                                                        .getDefaultMessage()));
        return toTaskVO(entity);
    }

    /* ------------------------------------------------------------ 片段 */

    @Override
    @Transactional(readOnly = true)
    public List<ChunkItemVO> listChunks(String docId, String q, String kind) {
        Long docFilter = docId == null || docId.isBlank() ? null : parseId(docId);
        String keyword = q == null || q.isEmpty() ? null : q;
        String kindFilter = kind == null || kind.isBlank() ? null : kind.trim();

        List<Chunk> rows = chunkRepository.findAllByOrderBySeqAscIdAsc();
        List<ChunkItemVO> result = new ArrayList<>();
        for (Chunk row : rows) {
            if (docFilter != null && !docFilter.equals(row.getDocId())) {
                continue;
            }
            if (kindFilter != null && !kindFilter.equals(row.getKind())) {
                continue;
            }
            // 大小写敏感的子串匹配，与契约 description 一致（前端也按 includes 过滤）。
            if (keyword != null && (row.getText() == null || !row.getText().contains(keyword))) {
                continue;
            }
            result.add(
                    new ChunkItemVO(
                            row.getChunkId(),
                            String.valueOf(row.getDocId()),
                            row.getDocTitle(),
                            row.getHeadingPath(),
                            row.getText(),
                            row.getStart(),
                            row.getEnd(),
                            KINDS.contains(row.getKind()) ? row.getKind() : Chunk.KIND_CHUNK,
                            Boolean.TRUE.equals(row.getVerified()),
                            row.getSeq() == null ? result.size() : row.getSeq()));
        }
        return result;
    }

    /* ------------------------------------------------------------ 轮询 */

    @Override
    @Transactional
    public void pollOnce() {
        List<IndexTask> running =
                indexTaskRepository.findByStatusInOrderByCreatedAtAsc(
                        List.of(IndexTask.STATUS_PENDING, IndexTask.STATUS_RUNNING));
        for (IndexTask task : running) {
            if (task.getExternalTaskId() == null || task.getExternalTaskId().isBlank()) {
                // 崩溃自愈：任务已落库但触发没走完，补一次触发。
                log.info("任务 {} 缺 external_task_id，补触发", task.getId());
                try {
                    triggerParse(task, indexableDocuments());
                } catch (RuntimeException ex) {
                    countFailure(task, ex);
                }
                continue;
            }
            try {
                AiIngestTask info = aiClient.getIngestTask(task.getExternalTaskId());
                apply(task, info);
            } catch (RuntimeException ex) {
                countFailure(task, ex);
            }
        }
    }

    /**
     * 把一次轮询结果写回任务；终态时收尾（写片段、翻资料状态、记 finishedAt）。
     *
     * @param task 任务实体
     * @param info Python 返回的进度
     */
    private void apply(IndexTask task, AiIngestTask info) {
        task.setPollFailures(0);
        String status = normalizeStatus(info.status(), task.getStatus());
        task.setStatus(status);
        task.setStage(normalizeStage(info.stage(), task.getStage()));
        task.setProgress(clampProgress(info.progress(), status));
        if (info.docCount() != null) {
            task.setDocCount(info.docCount());
        }
        if (info.chunkCount() != null) {
            task.setChunkCount(info.chunkCount());
        }
        if (IndexTask.STATUS_FAILED.equals(status)) {
            task.setError(truncate(info.error() == null ? "建库失败" : info.error()));
            task.setFinishedAt(Instant.now().getEpochSecond());
            indexTaskRepository.save(task);
            log.warn("建库任务 {} 失败：{}", task.getId(), task.getError());
            return;
        }
        if (IndexTask.STATUS_SUCCEEDED.equals(status)) {
            int written = persistChunks(task, info.chunks());
            task.setChunkCount(info.chunkCount() == null ? written : info.chunkCount());
            task.setProgress(100);
            task.setStage(IndexTask.STAGE_DONE);
            task.setFinishedAt(Instant.now().getEpochSecond());
            task.setError(null);
            if (task.getEmbeddingModel() == null || task.getEmbeddingModel().isBlank()) {
                task.setEmbeddingModel(properties.getIndex().getEmbeddingModel());
            }
            indexTaskRepository.save(task);
            int promoted = documentRepository.markStaleAsIndexed();
            log.info("建库任务 {} 成功：片段 {} 段，资料 {} 份转为 INDEXED", task.getId(), written, promoted);
            return;
        }
        indexTaskRepository.save(task);
    }

    /**
     * 落片段缓存：先清掉上一代产物，再写入本次的。
     *
     * @param task 成功任务
     * @param chunks Python 回传的片段
     * @return 实际写入条数
     */
    private int persistChunks(IndexTask task, List<AiChunk> chunks) {
        chunkRepository.deleteByTaskIdNot(task.getId());
        if (chunks == null || chunks.isEmpty()) {
            log.warn("任务 {} 成功但没回传片段，片段缓存保持为空", task.getId());
            return 0;
        }
        List<Chunk> entities = new ArrayList<>(chunks.size());
        Map<Long, Integer> perDoc = new HashMap<>();
        long now = Instant.now().getEpochSecond();
        int seq = 0;
        for (AiChunk source : chunks) {
            Long docId = parseId(source.docId());
            if (docId == null) {
                continue;
            }
            Chunk entity = new Chunk();
            entity.setTaskId(task.getId());
            entity.setChunkId(source.chunkId());
            entity.setDocId(docId);
            entity.setDocTitle(source.docTitle() == null ? "" : source.docTitle());
            entity.setHeadingPath(source.headingPath() == null ? "" : source.headingPath());
            entity.setText(source.text() == null ? "" : source.text());
            entity.setStart(source.start() == null ? 0 : source.start());
            entity.setEnd(source.end() == null ? 0 : source.end());
            entity.setKind(KINDS.contains(source.kind()) ? source.kind() : Chunk.KIND_CHUNK);
            entity.setVerified(source.verified() == null || source.verified());
            entity.setSeq(seq++);
            entity.setCreatedAt(now);
            entities.add(entity);
            perDoc.merge(docId, 1, Integer::sum);
        }
        chunkRepository.saveAll(entities);
        for (Map.Entry<Long, Integer> entry : perDoc.entrySet()) {
            documentRepository
                    .findByIdAndDeletedFalse(entry.getKey())
                    .ifPresent(
                            doc -> {
                                doc.setChunkCount(entry.getValue());
                                documentRepository.save(doc);
                            });
        }
        return entities.size();
    }

    /**
     * 轮询失败只计数，不立刻判死（手册 §J4：连续 30 次才 FAILED）。
     *
     * @param task 任务
     * @param ex 异常
     */
    private void countFailure(IndexTask task, RuntimeException ex) {
        int failures = (task.getPollFailures() == null ? 0 : task.getPollFailures()) + 1;
        task.setPollFailures(failures);
        if (failures >= IndexTask.MAX_POLL_FAILURES) {
            task.setStatus(IndexTask.STATUS_FAILED);
            task.setError(truncate("轮询连续失败 " + failures + " 次：" + ex.getMessage()));
            task.setFinishedAt(Instant.now().getEpochSecond());
            log.error("建库任务 {} 连续失败 {} 次，置 FAILED", task.getId(), failures);
        } else {
            log.warn("建库任务 {} 第 {} 次轮询失败，继续重试：{}", task.getId(), failures, ex.getMessage());
        }
        indexTaskRepository.save(task);
    }

    /* ------------------------------------------------------------ 工具 */

    /**
     * 参数校验。
     *
     * <p>刻意不用 Bean Validation：{@code @Min/@Max} 触发的是 40001，而契约要求 40002/40003 两个独立码。
     *
     * @param chunkSize 片段长度
     * @param overlap 重叠字数
     */
    private void validate(int chunkSize, int overlap) {
        if (chunkSize < MIN_CHUNK_SIZE || chunkSize > MAX_CHUNK_SIZE) {
            throw new ApiException(ErrorCode.INVALID_CHUNK_SIZE.getCode(), MSG_CHUNK_SIZE);
        }
        if (overlap < 0 || overlap >= chunkSize) {
            throw new ApiException(ErrorCode.INVALID_OVERLAP.getCode(), MSG_OVERLAP);
        }
    }

    /**
     * 待入库资料：未删除且未停用。
     *
     * @return 资料列表
     */
    private List<Document> indexableDocuments() {
        List<Document> all = documentRepository.findByDeletedFalseOrderByUpdatedAtDescIdDesc();
        List<Document> result = new ArrayList<>(all.size());
        for (Document doc : all) {
            if ("DISABLED".equals(doc.getStatus())) {
                continue;
            }
            result.add(doc);
        }
        return result;
    }

    /**
     * 从磁盘读正文。
     *
     * @param doc 资料
     * @return 正文；读不出来返回 null
     */
    private String readText(Document doc) {
        if (doc.getStorageKey() == null || doc.getStorageKey().isBlank()) {
            return null;
        }
        try (InputStream in = storage.read(doc.getStorageKey())) {
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException ex) {
            log.warn("读取资料 {} 的磁盘文件失败：{}", doc.getId(), ex.getMessage());
            return null;
        }
    }

    /**
     * Python 的 status 归一化到契约四值。
     *
     * @param raw 原始值
     * @param fallback 认不出来时保留的旧值
     * @return PENDING / RUNNING / SUCCEEDED / FAILED
     */
    private String normalizeStatus(String raw, String fallback) {
        if (raw == null || raw.isBlank()) {
            return fallback == null ? IndexTask.STATUS_RUNNING : fallback;
        }
        String upper = raw.trim().toUpperCase();
        return switch (upper) {
            case "PENDING", "QUEUED", "WAITING" -> IndexTask.STATUS_PENDING;
            case "SUCCEEDED", "SUCCESS", "DONE", "FINISHED", "COMPLETED" ->
                    IndexTask.STATUS_SUCCEEDED;
            case "FAILED", "ERROR", "FAILURE" -> IndexTask.STATUS_FAILED;
            case "RUNNING", "PROCESSING", "IN_PROGRESS" -> IndexTask.STATUS_RUNNING;
            default -> IndexTask.STATUS_RUNNING;
        };
    }

    /**
     * Python 的 stage 映射到契约五值白名单（手册 §J4 明令不许直出原始值）。
     *
     * @param raw 原始值
     * @param fallback 认不出来时保留的旧值
     * @return parsing / splitting / embedding / summarizing / done
     */
    private String normalizeStage(String raw, String fallback) {
        if (raw == null || raw.isBlank()) {
            return fallback == null ? IndexTask.STAGE_PARSING : fallback;
        }
        String lower = raw.trim().toLowerCase();
        if (STAGES.contains(lower)) {
            return lower;
        }
        if (lower.contains("done") || lower.contains("finish") || lower.contains("complete")) {
            return IndexTask.STAGE_DONE;
        }
        if (lower.contains("summar")) {
            return IndexTask.STAGE_SUMMARIZING;
        }
        if (lower.contains("embed") || lower.contains("vector") || lower.contains("index")) {
            return IndexTask.STAGE_EMBEDDING;
        }
        if (lower.contains("split") || lower.contains("chunk") || lower.contains("segment")) {
            return IndexTask.STAGE_SPLITTING;
        }
        if (lower.contains("pars") || lower.contains("load") || lower.contains("read")) {
            return IndexTask.STAGE_PARSING;
        }
        return fallback == null ? IndexTask.STAGE_PARSING : fallback;
    }

    /**
     * 进度归一到 0..100，终态恒 100。
     *
     * @param raw 原始进度
     * @param status 归一后的状态
     * @return 0..100
     */
    private int clampProgress(Integer raw, String status) {
        if (IndexTask.STATUS_SUCCEEDED.equals(status)) {
            return 100;
        }
        if (raw == null) {
            return 0;
        }
        return Math.max(0, Math.min(100, raw));
    }

    /**
     * manifest 快照：从最近成功任务还原。
     *
     * @param task 最近成功任务，可为 null
     * @return 快照；无成功任务时返回 null
     */
    private IndexManifestVO manifestOf(IndexTask task) {
        if (task == null) {
            return null;
        }
        return new IndexManifestVO(
                task.getEmbeddingModel(),
                task.getChunkSize(),
                task.getOverlap(),
                task.getDocCount(),
                task.getChunkCount(),
                task.getFinishedAt(),
                null);
    }

    /**
     * 任务实体转视图。
     *
     * @param entity 实体
     * @return 视图
     */
    private IndexTaskVO toTaskVO(IndexTask entity) {
        return new IndexTaskVO(
                String.valueOf(entity.getId()),
                entity.getStatus(),
                entity.getStage(),
                entity.getProgress(),
                entity.getChunkSize(),
                entity.getOverlap(),
                entity.getDocCount(),
                entity.getChunkCount(),
                entity.getCreatedAt(),
                entity.getFinishedAt(),
                entity.getError());
    }

    /**
     * 解析 id，非法返回 null。
     *
     * @param raw 原始串
     * @return Long 或 null
     */
    private Long parseId(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        try {
            return Long.valueOf(raw.trim());
        } catch (NumberFormatException ex) {
            return null;
        }
    }

    /**
     * 标签串拆成列表。
     *
     * @param tags 逗号分隔串
     * @return 列表，可能为空
     */
    private List<String> splitTags(String tags) {
        if (tags == null || tags.isBlank()) {
            return List.of();
        }
        List<String> result = new ArrayList<>();
        for (String item : tags.split(",")) {
            String trimmed = item.trim();
            if (!trimmed.isEmpty()) {
                result.add(trimmed);
            }
        }
        return result;
    }

    /**
     * 截断到 error 列宽上限。
     *
     * @param value 原文
     * @return 不超过 512 字符
     */
    private String truncate(String value) {
        if (value == null) {
            return null;
        }
        return value.length() <= 512 ? value : value.substring(0, 512);
    }
}
