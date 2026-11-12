package com.xiaoyi.rag.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
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
import com.xiaoyi.rag.model.entity.Experiment;
import com.xiaoyi.rag.model.entity.IndexTask;
import com.xiaoyi.rag.model.vo.ChunkItemVO;
import com.xiaoyi.rag.model.vo.IndexManifestVO;
import com.xiaoyi.rag.model.vo.IndexStatusVO;
import com.xiaoyi.rag.model.vo.IndexTaskVO;
import com.xiaoyi.rag.repository.ChunkRepository;
import com.xiaoyi.rag.repository.DocumentRepository;
import com.xiaoyi.rag.repository.ExperimentRepository;
import com.xiaoyi.rag.repository.IndexTaskRepository;
import com.xiaoyi.rag.service.IndexService;
import com.xiaoyi.rag.service.Storage;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 建库编排实现。
 *
 * <p>四个关键决策：
 *
 * <ul>
 *   <li><b>触发 parse 放在 rebuild 里同步做，而不是丢给轮询器。</b> 契约 {@code /api/v1/index/rebuild} 的 {@code
 *       x-error-codes} 明确包含 {@code 50301}——如果触发只发生在后台轮询里，这条路由永远回不出 50301， 前端就无法在「点重建」的当下告诉用户 Python
 *       挂了。 轮询器里保留同一条触发路径，纯粹用于崩溃自愈（任务已落库但 externalTaskId 还没写上）。
 *   <li><b>片段缓存按用户整代替换。</b> 成功后先删掉<b>本人</b>其他任务的全部片段再写入，避免两代产物混在一起 —— 这正是 {@code /index/status} 的
 *       needs_rebuild 语义所依赖的「当前缓存 == 最近一次成功」不变量。删除范围带 {@code user_id}， 否则一个用户建库会清空所有人的片段。
 *   <li><b>status 优先从本地库推导，Python 只用来判可用性。</b> docCount / chunkCount / 参数都取自本地，重启后仍准确； 若全部依赖
 *       Python， 它的任务表一丢，页面上的统计就归零了。
 *   <li><b>快照 + revision 决定「这次建库算不算数」。</b> 建库开始时把每份资料的 {@code (id, revision)} 存进 {@code
 *       index_task.snapshot_json}，收尾时逐份用 {@code where revision = :snapshot} 原子落库：
 *       建库期间用户改了标题/标签/正文，revision 已变，那条 update 影响 0 行，片段不覆盖、状态不翻转。这就是
 *       H3「建库期间新上传资料仍为待建、失败不破坏上一代」的实现点。
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

    /** 实验的非终态取值，与 {@code ExperimentServiceImpl} 落库时用的一致。 */
    private static final String EXPERIMENT_STATUS_PENDING = "PENDING";

    private static final String EXPERIMENT_STATUS_RUNNING = "RUNNING";

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

    private final ObjectMapper objectMapper;

    /**
     * 参数实验仓库：只用来判「现在有没有实验在跑」。
     *
     * <p>刻意注入 {@code ExperimentRepository} 而不是 {@code ExperimentService}： 实验侧也要调 {@link
     * #rebuild}（chunkSize/overlap 轴必须真重建索引）， 两个 Service 互相注入会形成循环依赖，Spring 只能靠 {@code @Lazy} 打补丁。
     * 这里只需要一次状态查询，走仓库是最短路径。
     */
    private final ExperimentRepository experimentRepository;

    public IndexServiceImpl(
            IndexTaskRepository indexTaskRepository,
            DocumentRepository documentRepository,
            ChunkRepository chunkRepository,
            AiServiceClient aiClient,
            Storage storage,
            XiaoyiProperties properties,
            ObjectMapper objectMapper,
            ExperimentRepository experimentRepository) {
        this.indexTaskRepository = indexTaskRepository;
        this.documentRepository = documentRepository;
        this.chunkRepository = chunkRepository;
        this.aiClient = aiClient;
        this.storage = storage;
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.experimentRepository = experimentRepository;
    }

    /* ------------------------------------------------------------ 状态 */

    @Override
    @Transactional(readOnly = true)
    public IndexStatusVO status(Long userId) {
        List<Document> docs =
                documentRepository.findByUploadedByAndDeletedFalseOrderByUpdatedAtDescIdDesc(
                        userId);
        Optional<IndexTask> lastOk =
                indexTaskRepository.findFirstByUserIdAndStatusOrderByFinishedAtDescIdDesc(
                        userId, IndexTask.STATUS_SUCCEEDED);

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
        int chunkCount = (int) chunkRepository.countByUserId(userId);

        // Python 是否活着只影响 status 取值，不影响本次响应能否成功（unavailable 也是 HTTP 200）。
        AiIndexManifest manifest;
        try {
            manifest = aiClient.getIndexManifest(userId);
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
                    manifestOf(lastOk.orElse(null), embeddingModel));
        }

        List<String> stale = new ArrayList<>();
        for (Document doc : docs) {
            if (STALE_DOC_STATUS.contains(doc.getStatus())) {
                stale.add(doc.getTitle() == null ? doc.getFilename() : doc.getTitle());
            }
        }
        // embedding 模型名以 Python 的 manifest 为准：真正做向量化的是它，Java 这边的
        // 配置只是「本次任务登记时以为用的是谁」。两者不一致时若继续报 Java 侧的值，
        // 前端会显示一个从没跑过的模型名（实测容器栈里曾长期显示 mock-embedding，
        // 而 Milvus 里存的是 2048 维的 embedding-3 向量）。
        String reportedModel =
                manifest != null
                                && manifest.embeddingModel() != null
                                && !manifest.embeddingModel().isBlank()
                        ? manifest.embeddingModel()
                        : embeddingModel;
        if (!stale.isEmpty()) {
            return new IndexStatusVO(
                    "needs_rebuild",
                    docCount,
                    chunkCount,
                    chunkSize,
                    overlap,
                    reportedModel,
                    lastBuiltAt,
                    stale.size() + " 份资料尚未入库",
                    manifestOf(lastOk.orElse(null), reportedModel));
        }
        if (lastOk.isEmpty()) {
            return new IndexStatusVO(
                    "needs_rebuild",
                    docCount,
                    chunkCount,
                    chunkSize,
                    overlap,
                    reportedModel,
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
                    reportedModel,
                    lastBuiltAt,
                    "建库参数已变更",
                    manifestOf(lastOk.get(), reportedModel));
        }
        return new IndexStatusVO(
                "ready",
                docCount,
                chunkCount,
                chunkSize,
                overlap,
                reportedModel,
                lastBuiltAt,
                null,
                manifestOf(lastOk.get(), reportedModel));
    }

    /* ------------------------------------------------------------ 重建 */

    @Override
    @Transactional
    public IndexTaskVO rebuild(Long userId, RebuildRequest request) {
        // 实验进行中拒绝建库：参数实验每一组都要先按本组 chunkSize/overlap 重建索引，
        // 若允许用户此刻手动重建，会把正在测量的向量库换掉，实验结论就不可信。
        // 与 40903 分开：一个是「已有建库任务」，一个是「已有实验在执行」，前端文案不同。
        List<Experiment> activeExperiments =
                experimentRepository.findByStatusIn(
                        List.of(EXPERIMENT_STATUS_PENDING, EXPERIMENT_STATUS_RUNNING));
        if (!activeExperiments.isEmpty()) {
            throw new ApiException(
                    ErrorCode.EXPERIMENT_ALREADY_RUNNING.getCode(),
                    ErrorCode.EXPERIMENT_ALREADY_RUNNING.getDefaultMessage());
        }
        return accept(userId, request);
    }

    /**
     * 实验通道：同一套受理逻辑，只跳过「已有实验在执行」的互斥。
     *
     * <p>实验自己就是那个「正在执行的实验」，走 {@link #rebuild} 会被自己挡住（40902）。 建库任务本身的串行锁（40903）仍然生效 ——
     * 一组实验的重建没跑完就开下一组，属于编排 bug。
     */
    @Override
    @Transactional
    public IndexTaskVO rebuildForExperiment(Long userId, RebuildRequest request) {
        return accept(userId, request);
    }

    /**
     * 受理一次重建：参数校验 → 并发锁 → 落库任务 → 触发 Python。
     *
     * @param userId 归属用户
     * @param request 片段长度与重叠字数
     * @return 新建任务视图
     */
    private IndexTaskVO accept(Long userId, RebuildRequest request) {
        int chunkSize =
                request == null || request.chunkSize() == null
                        ? properties.getIndex().getDefaultChunkSize()
                        : request.chunkSize();
        int overlap =
                request == null || request.overlap() == null
                        ? properties.getIndex().getDefaultOverlap()
                        : request.overlap();
        validate(chunkSize, overlap);

        // 建库串行（按用户）：已有在跑的任务就直接 409，别让两次重建互相覆盖片段缓存。
        List<IndexTask> running =
                indexTaskRepository.findByUserIdAndStatusInOrderByCreatedAtDesc(
                        userId, List.of(IndexTask.STATUS_PENDING, IndexTask.STATUS_RUNNING));
        if (!running.isEmpty()) {
            throw new ApiException(
                    ErrorCode.INDEX_TASK_ALREADY_RUNNING.getCode(),
                    ErrorCode.INDEX_TASK_ALREADY_RUNNING.getDefaultMessage());
        }

        List<Document> docs = indexableDocuments(userId);
        long now = Instant.now().getEpochSecond();
        IndexTask task = new IndexTask();
        task.setUserId(userId);
        task.setGeneration(UUID.randomUUID().toString());
        task.setSubmissionKey(UUID.randomUUID().toString());
        task.setSnapshotJson(snapshotJson(docs));
        task.setStatus(IndexTask.STATUS_PENDING);
        task.setStage(IndexTask.STAGE_PARSING);
        task.setProgress(0);
        task.setChunkSize(chunkSize);
        task.setOverlap(overlap);
        task.setEmbeddingModel(properties.getIndex().getEmbeddingModel());
        task.setDocCount(docs.size());
        task.setChunkCount(0);
        task.setPollFailures(0);
        task.setCreatedAt(now);
        IndexTask saved;
        try {
            saved = indexTaskRepository.saveAndFlush(task);
        } catch (DataIntegrityViolationException ex) {
            // uk_index_task_active_user：同一用户同时只允许一个非终态任务。上面的预检查有并发窗口，
            // 库层唯一键才是最终判据，这里把它翻译成同一个 40903。
            throw new ApiException(
                    ErrorCode.INDEX_TASK_ALREADY_RUNNING.getCode(),
                    ErrorCode.INDEX_TASK_ALREADY_RUNNING.getDefaultMessage());
        }

        if (docs.isEmpty()) {
            // 全量重建当前空语料 = 空索引：没有资料可送，Python 的 ParseRequest 要求 documents 至少 1 条，
            // 硬送会拿到 400 并被翻成 50301。这里直接把任务收成 SUCCEEDED，并清掉本人上一代片段，
            // 语义与「重建成功但没有内容」一致，也不会在索引清单里留下上一代的残影。
            finishEmptyRebuild(saved);
            return toTaskVO(saved);
        }

        triggerParse(saved, docs);
        return toTaskVO(saved);
    }

    /**
     * 空语料重建的收尾：任务直接 SUCCEEDED，片段缓存清空，资料集本来就是空所以无需翻状态。
     *
     * @param task 已落库的任务
     */
    private void finishEmptyRebuild(IndexTask task) {
        persistChunks(task, List.of());
        task.setStatus(IndexTask.STATUS_SUCCEEDED);
        task.setStage(IndexTask.STAGE_DONE);
        task.setProgress(100);
        task.setChunkCount(0);
        task.setDocCount(0);
        task.setError(null);
        task.setFinishedAt(Instant.now().getEpochSecond());
        indexTaskRepository.save(task);
        log.info("建库任务 {} 空语料重建完成：已清空本人上一代片段", task.getId());
    }

    /**
     * 调 Python 触发入库并把 external_task_id 写回任务。
     *
     * <p>失败时任务置 FAILED 并抛 {@code 50301}：重建这个动作在用户视角是「点一下」， 触发都失败就没必要留一个永远 PENDING 的任务让前端轮询到超时。
     *
     * <p>{@code submissionKey} 来自任务本身而不是现场生成：触发超时后轮询器会重放同一次提交， Python 侧按 {@code (user_id,
     * submission_key)} 去重，重试拿到的是同一个 task_id，不会重复切片段。
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
                            task.getUserId(),
                            new AiParseRequest(
                                    items,
                                    task.getChunkSize(),
                                    task.getOverlap(),
                                    task.getSubmissionKey(),
                                    task.getGeneration(),
                                    // N3：显式传 true 而不是靠默认值。摘要卡是搜索质量的
                                    // 一部分，默认关闭过一次就再没人打开；要关得显式关。
                                    true));
        } catch (RuntimeException ex) {
            // 带上异常本体：只打 getMessage() 时，Connection reset 这类网络失败在日志里
            // 只剩一句「Python AI request failed」，没有堆栈就分不清是超时、连不上还是对端关连接。
            log.error("触发建库失败：{} - {}", ex.getClass().getSimpleName(), ex.getMessage(), ex);
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
    public IndexTaskVO task(Long userId, String id) {
        Long taskId = parseId(id);
        if (taskId == null) {
            throw new ApiException(
                    ErrorCode.INDEX_TASK_NOT_FOUND.getCode(),
                    ErrorCode.INDEX_TASK_NOT_FOUND.getDefaultMessage());
        }
        IndexTask entity =
                indexTaskRepository
                        .findByIdAndUserId(taskId, userId)
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
    public List<ChunkItemVO> listChunks(Long userId, String docId, String q, String kind) {
        Long docFilter = docFilterOf(docId);
        String keyword = q == null || q.isEmpty() ? null : q;
        String kindFilter = kind == null || kind.isBlank() ? null : kind.trim();

        List<Chunk> rows = chunkRepository.findByUserIdOrderBySeqAscIdAsc(userId);
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
                            docIdLabel(row.getDocId()),
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

    /**
     * 库里 `doc_id = 0` 的片段是摘要卡（见 {@link Chunk#SUMMARY_DOC_ID}），对外要还原成 Python 侧的哨兵字符串
     * `"__summary__"`。
     *
     * <p>契约里 `ChunkItem.docId` 是 `EntityId`（字符串或正整数），给 `0` 会直接违约。
     *
     * @param docId 库里的 doc_id
     * @return 对外展示的 docId
     */
    private static String docIdLabel(Long docId) {
        if (docId == null) {
            return "";
        }
        return docId == Chunk.SUMMARY_DOC_ID ? Chunk.SUMMARY_DOC_LABEL : String.valueOf(docId);
    }

    /**
     * 把 `?docId=` 参数翻译成库里的过滤值。
     *
     * <p>要认三个输入：空串（不过滤）、`"__summary__"`（只看摘要卡，翻成 0）、普通数字 id。 不认 `"__summary__"`
     * 的话，前端点「只看摘要」会静默返回空列表 —— 看起来像「没有摘要卡」。
     *
     * @param docId 查询参数
     * @return 库里的 doc_id；空串返回 null（不过滤）
     */
    private Long docFilterOf(String docId) {
        if (docId == null || docId.isBlank()) {
            return null;
        }
        if (Chunk.SUMMARY_DOC_LABEL.equals(docId.trim())) {
            return Chunk.SUMMARY_DOC_ID;
        }
        Long parsed = parseId(docId);
        // 解析不了（比如 "abc"）就当「不匹配任何行」：回 0 比回全部安全得多，
        // 后者会让前端以为过滤没生效。
        return parsed == null ? -1L : parsed;
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
                // 崩溃自愈：任务已落库但触发没走完，补一次触发。资料范围取自快照，
                // 不能用「当前全部可入库资料」——那会把建库期间新上传的资料混进这一代。
                log.info("任务 {} 缺 external_task_id，补触发", task.getId());
                try {
                    triggerParse(task, snapshotDocuments(task));
                } catch (RuntimeException ex) {
                    countFailure(task, ex);
                }
                continue;
            }
            try {
                AiIngestTask info =
                        aiClient.getIngestTask(task.getUserId(), task.getExternalTaskId());
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
            int marked = documentRepository.markFailedForOwner(task.getUserId(), task.getError());
            log.warn("建库任务 {} 失败：{}（{} 份资料置 FAILED）", task.getId(), task.getError(), marked);
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
            int promoted = promoteDocuments(task, info.chunks());
            log.info("建库任务 {} 成功：片段 {} 段，资料 {} 份转为 INDEXED", task.getId(), written, promoted);
            return;
        }
        indexTaskRepository.save(task);
    }

    /**
     * 落片段缓存：先清掉本人上一代产物，再写入本次的。
     *
     * <p>删除条件带 {@code user_id}：片段表是全用户共用的，漏掉这个条件等于每次建库都把别人的知识库清空。
     *
     * @param task 成功任务
     * @param chunks Python 回传的片段
     * @return 实际写入条数
     */
    private int persistChunks(IndexTask task, List<AiChunk> chunks) {
        chunkRepository.deleteByUserIdAndTaskIdNot(task.getUserId(), task.getId());
        if (chunks == null || chunks.isEmpty()) {
            log.warn("任务 {} 成功但没回传片段，片段缓存保持为空", task.getId());
            return 0;
        }
        List<Chunk> entities = new ArrayList<>(chunks.size());
        long now = Instant.now().getEpochSecond();
        int seq = 0;
        for (AiChunk source : chunks) {
            Long docId = chunkDocId(source);
            if (docId == null) {
                continue;
            }
            Chunk entity = new Chunk();
            entity.setTaskId(task.getId());
            entity.setUserId(task.getUserId());
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
        }
        chunkRepository.saveAll(entities);
        return entities.size();
    }

    /**
     * 片段归属的资料 id。
     *
     * <p>摘要卡（N3）的 `doc_id` 是 Python 侧的哨兵字符串 `"__summary__"`，而 `chunk.doc_id` 是 `BIGINT NOT
     * NULL`。这里把哨兵翻成 {@link Chunk#SUMMARY_DOC_ID}（0），对外输出时 再由 {@code listChunks} 翻回去。
     *
     * <p>**不能直接 `parseId` 后跳过**：那会把摘要卡整条丢掉 —— 现象是「建库成功、任务 chunkCount 含卡片、但片段列表里一张都没有」，极难查。
     *
     * @param source Python 回传的片段
     * @return 落库用的 docId；非摘要卡且 docId 非法时返回 null（该条跳过）
     */
    private Long chunkDocId(AiChunk source) {
        if (Chunk.KIND_SUMMARY.equals(source.kind()) || Chunk.KIND_RULE.equals(source.kind())) {
            return Chunk.SUMMARY_DOC_ID;
        }
        return parseId(source.docId());
    }

    /**
     * 把快照里「未被改动」的资料原子翻成 INDEXED。
     *
     * <p>逐份比对 {@code revision}：建库期间被改过的资料影响 0 行，状态留在 NEEDS_REBUILD，等下一次重建 ——
     * 这就是「失败/过期不破坏上一代、新上传仍为待建」的落点。
     *
     * @param task 成功任务（携带快照）
     * @param chunks 本次回传片段，用于统计每份资料的片段数
     * @return 成功翻状态的数量
     */
    private int promoteDocuments(IndexTask task, List<AiChunk> chunks) {
        Map<Long, Long> revisions = snapshotRevisions(task.getSnapshotJson());
        if (revisions.isEmpty()) {
            log.warn("任务 {} 缺快照，跳过资料状态翻转", task.getId());
            return 0;
        }
        Map<Long, Integer> perDoc = new HashMap<>();
        if (chunks != null) {
            for (AiChunk source : chunks) {
                Long docId = parseId(source.docId());
                if (docId != null) {
                    perDoc.merge(docId, 1, Integer::sum);
                }
            }
        }
        long now = Instant.now().getEpochSecond();
        int promoted = 0;
        for (Map.Entry<Long, Long> entry : revisions.entrySet()) {
            Long docId = entry.getKey();
            Integer count = perDoc.get(docId);
            if (count == null) {
                // 这份资料没产出片段（正文读不出来 / 已被删除），保持原状态，别假装它入库成功。
                continue;
            }
            int affected =
                    documentRepository.markSnapshotIndexed(
                            task.getUserId(), docId, entry.getValue(), count, now);
            if (affected > 0) {
                promoted++;
            } else {
                log.info("资料 {} 在快照后被改动，保留待建状态", docId);
            }
        }
        return promoted;
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

    /* ------------------------------------------------------------ 快照 */

    /**
     * 快照序列化：只存 {@code id + revision}，够用来判断「这份资料还是不是当时那一份」。
     *
     * @param docs 本次参与建库的资料
     * @return JSON 数组串
     */
    private String snapshotJson(List<Document> docs) {
        List<Map<String, Object>> rows = new ArrayList<>(docs.size());
        for (Document doc : docs) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", doc.getId());
            row.put("revision", doc.getRevision() == null ? 0L : doc.getRevision());
            rows.add(row);
        }
        try {
            return objectMapper.writeValueAsString(rows);
        } catch (JsonProcessingException ex) {
            log.warn("序列化建库快照失败：{}", ex.getMessage());
            return "[]";
        }
    }

    /**
     * 快照反序列化。
     *
     * @param json 快照串
     * @return 资料 id → 当时的 revision；坏数据返回空表（调用方按「无快照」处理）
     */
    private Map<Long, Long> snapshotRevisions(String json) {
        Map<Long, Long> result = new LinkedHashMap<>();
        if (json == null || json.isBlank()) {
            return result;
        }
        try {
            JsonNode root = objectMapper.readTree(json);
            if (root == null || !root.isArray()) {
                return result;
            }
            for (JsonNode node : root) {
                long id = node.path("id").asLong(0L);
                if (id > 0) {
                    result.put(id, node.path("revision").asLong(0L));
                }
            }
        } catch (JsonProcessingException ex) {
            log.warn("解析建库快照失败：{}", ex.getMessage());
        }
        return result;
    }

    /**
     * 按快照取回资料实体（补触发用）。
     *
     * @param task 任务
     * @return 仍存在且属于本人的资料
     */
    private List<Document> snapshotDocuments(IndexTask task) {
        List<Document> result = new ArrayList<>();
        for (Long docId : snapshotRevisions(task.getSnapshotJson()).keySet()) {
            documentRepository
                    .findByIdAndUploadedByAndDeletedFalse(docId, task.getUserId())
                    .ifPresent(result::add);
        }
        return result;
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
     * 待入库资料：本人的、未删除且未停用。
     *
     * @param userId 归属人
     * @return 资料列表
     */
    private List<Document> indexableDocuments(Long userId) {
        List<Document> all =
                documentRepository.findByUploadedByAndDeletedFalseAndStatusNot(userId, "DISABLED");
        return all;
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
     * <p>{@code embeddingModel} 由调用方传入，而不是直接读任务登记值：Python 的 manifest 才是
     * 「实际用的哪个模型」的权威来源，两者不一致时要让快照也反映真实值，否则前端拿到的 顶层字段与 manifest 自相矛盾。
     *
     * @param task 最近成功任务，可为 null
     * @param embeddingModel 对外报告的模型名
     * @return 快照；无成功任务时返回 null
     */
    private IndexManifestVO manifestOf(IndexTask task, String embeddingModel) {
        if (task == null) {
            return null;
        }
        return new IndexManifestVO(
                embeddingModel,
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
