/**
 * 对外 API 契约模型（手写最小集）
 *
 * 说明：docs/api/openapi-public.yaml 尚未生成。该文件当前由手写维护，
 *       YAML 就绪后执行 `npm run gen:api` 由 openapi-typescript 生成并替换本文件，
 *       业务代码只依赖本文件导出的类型，不感知生成方式。
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
  questionIds: string[];
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
