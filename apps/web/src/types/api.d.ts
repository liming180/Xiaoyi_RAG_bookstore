/**
 * 对外 API 契约模型（手写视图层）
 *
 * 契约唯一源头是 docs/api/openapi-public.yaml；`npm run gen:api` 生成
 * src/types/api.generated.ts（机器可读、含全部 schema 与 operation）。
 * 本文件是业务代码实际使用的视图模型：把契约里的 `string | number` 收窄成 string、
 * 把可空字段显式标成 `| null`、把枚举拍平成字符串字面量，便于组件消费。
 *
 * 两边的属性名由 `npm run check:contract`（scripts/check-contract-drift.mjs）比对：
 * 契约新增字段而这里漏掉 → 门禁失败。类型差异属于有意收窄，不参与比对。
 *
 * 命名约定：TS 侧统一 camelCase；线上可能出现的 snake_case（doc_title / heading_path /
 *          chunk_id 等）由 src/api/normalize.ts 统一归一，业务层不处理。
 */

/** 统一响应包装：{ code, message, data, timestamp } */
export interface Result<T> {
  code: number;
  message: string;
  data: T;
  timestamp: number;
}

/** 分页包装 */
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

/* ------------------------------------------------------------------ 鉴权 */

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResult {
  token: string;
  expiresIn: number;
  user: UserInfo;
}

export interface UserInfo {
  id: number;
  username: string;
  displayName: string;
  /** 角色。ADMIN 唯一，决定登录后落管理端还是用户端（V11 新增） */
  role: UserRole;
}

/** 系统角色。ADMIN 全系统只有一个账号，且不提供创建入口。 */
export type UserRole = 'ADMIN' | 'USER';

/* -------------------------------------------------------- 管理端用户管理 */

/** 管理端用户行（AdminUserItem） */
export interface AdminUserItem {
  id: number;
  username: string;
  /** NULL 时回退显示 username */
  displayName: string | null;
  role: UserRole;
  deleted: boolean;
  /** Unix 秒 */
  createdAt: number;
}

export interface AdminUserPage {
  items: AdminUserItem[];
  total: number;
  page: number;
  size: number;
}

export interface AdminUserCreateRequest {
  username: string;
  password: string;
  displayName?: string;
}

export interface AdminUserUpdateRequest {
  displayName: string;
}

export interface AdminUserPasswordRequest {
  newPassword: string;
}

/* -------------------------------------------------------- 管理端审计日志 */

/** 管理端审计行（AdminAuditItem） */
export interface AdminAuditItem {
  id: number;
  /** 操作者 id；历史行可能为 null */
  operatorId: number | null;
  /** 操作者 username；账号不存在时为 null，页面显示「—」 */
  operatorName: string | null;
  /** 动作名，如 admin.user.create */
  action: string;
  /** 操作对象，如 user:7 */
  target: string | null;
  /** 详情 JSON 原文（写入时快照，不做二次解释） */
  detailJson: string | null;
  /** Unix 秒 */
  createdAt: number;
}

export interface AdminAuditPage {
  items: AdminAuditItem[];
  total: number;
  page: number;
  size: number;
}

/* ---------------------------------------------------------------- 会话 */

export interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messageCount: number;
}

export type CitationKind = 'chunk' | 'summary' | 'rule';

/** 引用片段。ref 为回答正文里的编号（1..k），chunkId 形如 D02-C001 */
export interface Citation {
  ref: number | string;
  chunkId: string;
  docId: string;
  docTitle: string;
  headingPath: string;
  /** 摘录正文（后端给的是片段原文，前端按需截断展示） */
  text: string;
  start: number;
  end: number;
  /** 相似度得分 0..1 */
  score: number;
  stage?: string;
  kind: CitationKind;
  /** 未核实资料（F11） */
  verified: boolean;
}

/** F08 检索过程：一条 = 一个候选片段 */
export interface TraceRow {
  rank: number;
  chunkId: string;
  docId: string;
  docTitle: string;
  headingPath: string;
  text: string;
  start: number;
  end: number;
  score: number;
  retrieved: boolean;
  kind: CitationKind;
  verified: boolean;
}

export interface RetrievalTrace {
  question: string;
  k: number;
  chunkSize: number;
  overlap: number;
  rows: TraceRow[];
}

export type MessageRole = 'user' | 'assistant';

export interface Message {
  id: string;
  conversationId: string;
  role: MessageRole;
  content: string;
  createdAt: number;
  citations: Citation[];
  trace: RetrievalTrace | null;
  usage: Record<string, number> | null;
  elapsedMs: number | null;
  degraded: boolean;
  /** B1 追问推荐（0-3 条，可能缺失） */
  suggestions: string[];
  /** C1 反馈状态 */
  feedback: 'up' | 'down' | null;
  error?: string | null;
}

export type AnswerMode = 'rag' | 'direct' | 'both';

export interface ChatRequest {
  conversationId: string;
  question: string;
  mode: AnswerMode;
  k: number;
}

/* ------------------------------------------------------- SSE 事件（§7.5） */

export type StreamStage = 'rewriting' | 'retrieving' | 'reranking' | 'generating';

export interface StatusEvent {
  event: 'status';
  data: { stage: StreamStage };
}

export interface RetrievalEvent {
  event: 'retrieval';
  data: { citations: Citation[] };
}

export interface TokenEvent {
  event: 'token';
  data: { content: string };
}

export interface DoneEvent {
  event: 'done';
  data: {
    messageId: string;
    usage?: Record<string, number>;
    elapsedMs?: number;
    degraded?: boolean;
    suggestions?: string[];
    /** both 模式下第二份回答（direct 侧） */
    directMessageId?: string;
    directContent?: string;
  };
}

export interface ErrorEvent {
  event: 'error';
  data: { code: number; message: string; fallback?: string };
}

/** 未知事件原样透传，前端状态机对未知事件做 identity */
export interface UnknownEvent {
  event: string;
  data: unknown;
}

export type ChatStreamEvent =
  | StatusEvent
  | RetrievalEvent
  | TokenEvent
  | DoneEvent
  | ErrorEvent
  | UnknownEvent;

/* ---------------------------------------------------------------- 资料 */

export type DocumentStatus =
  | 'UPLOADING'
  | 'PARSING'
  | 'INDEXED'
  | 'FAILED'
  | 'NEEDS_REBUILD'
  | 'DISABLED';

export interface DocumentMeta {
  id: string;
  name: string;
  title: string;
  tags: string[];
  version: string;
  charCount: number;
  chunkCount: number;
  status: DocumentStatus;
  verified: boolean;
  updatedAt: number;
  error?: string | null;
}

export interface UploadSkipped {
  name: string;
  reason: string;
}

export interface UploadResult {
  accepted: DocumentMeta[];
  skipped: UploadSkipped[];
}

/* ---------------------------------------------------------------- 建库 */

export type IndexStatusValue = 'ready' | 'needs_rebuild' | 'unavailable';

/** 最近一次成功建库的清单快照（契约 IndexManifest，字段全可选） */
export interface IndexManifest {
  embeddingModel?: string;
  chunkSize?: number;
  overlap?: number;
  docCount?: number;
  chunkCount?: number;
  /** Unix 秒 */
  builtAt?: number;
  sha256?: string;
}

export interface IndexStatus {
  status: IndexStatusValue;
  docCount: number;
  chunkCount: number;
  chunkSize: number;
  overlap: number;
  embeddingModel: string;
  lastBuiltAt: number | null;
  /** 待重建原因，用于横幅补充说明 */
  reason?: string | null;
  /** 上次建库的清单快照；从未建库时缺失 */
  manifest?: IndexManifest | null;
}

export type IndexTaskStatus = 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';
export type IndexTaskStage = 'parsing' | 'splitting' | 'embedding' | 'summarizing' | 'done';

export interface IndexTask {
  id: string;
  status: IndexTaskStatus;
  stage: IndexTaskStage;
  /** 0..100 */
  progress: number;
  chunkSize: number;
  overlap: number;
  docCount: number;
  chunkCount: number;
  error?: string | null;
  startedAt: number;
  finishedAt: number | null;
}

export interface RebuildRequest {
  chunkSize: number;
  overlap: number;
}

/* ---------------------------------------------------------------- 片段 */

export interface ChunkItem {
  chunkId: string;
  docId: string;
  docTitle: string;
  headingPath: string;
  text: string;
  start: number;
  end: number;
  kind: CitationKind;
  verified: boolean;
  index: number;
}

export interface ChunkQuery {
  docId?: string;
  q?: string;
  kind?: CitationKind;
}

/* ---------------------------------------------------------------- 评测 */

export interface EvalQuestion {
  id: string;
  type: string;
  question: string;
  keywords: string;
  evidence: string;
  /** 是否参与选题（P5-08）；停用题仍留在题库与历史快照里 */
  enabled: boolean;
  /** seed 内置种子 / manual 手工新增 / import CSV 导入 / generated 自动生成 */
  source: string;
}

export interface EvalCaseResult {
  questionId: string;
  type: string;
  question: string;
  directAnswer: string;
  directPassed: boolean;
  ragAnswer: string;
  ragPassed: boolean;
  ragSources: string[];
  elapsedMs: number;
}

export interface EvalStats {
  total: number;
  passedDirect: number;
  passedRag: number;
}

export interface EvalRunSummary {
  id: string;
  createdAt: number;
  finishedAt: number | null;
  status: 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';
  progress: number;
  stats: EvalStats | null;
  mode: AnswerMode;
  k: number;
}

export interface EvalRun extends EvalRunSummary {
  cases: EvalCaseResult[];
}

export interface EvalBatchRequest {
  /** 精确点选的题号；空数组 = 让服务端按 types / sample / limit 筛选 */
  questionIds: string[];
  /** 题型筛选（single / cross / out）；空 = 全部题型 */
  types?: string[];
  /** 最多测几道；null / 0 = 不限 */
  limit?: number | null;
  /** true = 随机抽样，false / 缺省 = 按题库顺序 */
  sample?: boolean;
  mode: AnswerMode;
  k: number;
}

/* ---------------------------------------------------------------- 反馈 */

export type FeedbackRating = 'up' | 'down';

export interface FeedbackRequest {
  rating: FeedbackRating;
  tags?: string[];
  comment?: string;
}

export interface FeedbackSummary {
  total: number;
  up: number;
  down: number;
  candidates: number;
}

export interface EvalCandidate {
  id: string;
  question: string;
  source: 'feedback' | 'manual';
  status: 'pending' | 'accepted' | 'ignored';
  createdAt: number;
  /**
   * 人工补的判分关键词（语法同 `assets/eval/keywords.csv`）。
   *
   * `null` = 未补：该候选可以进实验，但标 `scored:false`，不计入 hitRate 分母。
   * 前端据此在候选池提示「采纳后能不能计分」。
   */
  keywords: string | null;
}

/* -------------------------------------------------------------- 参数实验 */

export interface ExperimentAxis {
  chunkSize: number[];
  overlap: number[];
  k: number[];
  rerank: boolean[];
  summary: boolean[];
}

export interface ExperimentParams {
  chunkSize: number;
  overlap: number;
  k: number;
  rerank: boolean;
  summary: boolean;
}

export interface ExperimentMetrics {
  hitRate: number;
  avgElapsedMs: number;
  avgSources: number;
  failed: number;
  /**
   * 本组哪几根轴真的生效。
   *
   * `summary` 在全局摘要卡落地前恒为 `false`：参数能填、能落库，但建库管线不生成
   * 摘要卡，两组跑出来完全一样。对比表按这一栏灰显未生效的轴。
   */
  effective?: ExperimentEffective;
  /** 计入 hitRate 分母的题数（有判分关键词的题） */
  scored?: number;
  /** 进了实验但没计分的题数（候选题未填关键词） */
  unscored?: number;
  /** 本组失败原因；仅该组失败时出现，不影响其它组 */
  error?: string;
}

/** 每根轴在本组是否真生效。 */
export interface ExperimentEffective {
  k?: boolean;
  rerank?: boolean;
  chunkSize?: boolean;
  overlap?: boolean;
  summary?: boolean;
}

export interface ExperimentRun {
  id: string;
  params: ExperimentParams;
  metrics: ExperimentMetrics;
  elapsedMs: number;
}

export interface Experiment {
  id: string;
  name: string;
  status: 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';
  progress: number;
  totalGroups: number;
  finishedGroups: number;
  createdAt: number;
  finishedAt: number | null;
  error?: string | null;
}

export interface ExperimentReport {
  experiment: Experiment;
  runs: ExperimentRun[];
}
