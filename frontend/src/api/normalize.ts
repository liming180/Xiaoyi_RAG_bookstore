import type {
  Citation,
  CitationKind,
  DocumentMeta,
  IndexManifest,
  IndexStatus,
  Message,
  RetrievalTrace,
  TraceRow,
} from '@/types/api';

/**
 * 契约归一化层。
 *
 * 契约源头是 docs/api/openapi-public.yaml（`npm run gen:api` 生成 api.generated.ts）。
 * 归一化仍保留，是因为历史 mock/种子数据与线上偶发的 snake_case（chunk_id / doc_title /
 * heading_path）需要统一成 camelCase 的视图模型：
 *   - 规格 §7.5：{ ref: "D02-C001", docTitle, headingPath, chunk, start, end, score, stage }
 *   - 功能规格 F05：{ ref: 1, chunk_id, source, score, start, end, text }
 * 归一化只做「读」方向的兼容，绝不改后端字段。
 */

type Dict = Record<string, unknown>;

const isDict = (v: unknown): v is Dict => typeof v === 'object' && v !== null && !Array.isArray(v);

const str = (v: unknown, fallback = ''): string => (typeof v === 'string' ? v : fallback);

const num = (v: unknown, fallback = 0): number => {
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v);
  return fallback;
};

const bool = (v: unknown, fallback = true): boolean => (typeof v === 'boolean' ? v : fallback);

const arr = <T>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);

/** 取第一个存在的键（同时兼容 camelCase 与 snake_case） */
const pick = (o: Dict, ...keys: string[]): unknown => {
  for (const key of keys) {
    if (o[key] !== undefined && o[key] !== null) return o[key];
  }
  return undefined;
};

const normalizeKind = (v: unknown): CitationKind => {
  const s = str(v, 'chunk');
  return s === 'summary' || s === 'rule' ? s : 'chunk';
};

/** D02-C001 形式的片段 ID */
const CHUNK_ID_RE = /^D\d{2}-C\d{3}$/i;

export function normalizeCitation(input: unknown, index = 0): Citation {
  const o = isDict(input) ? input : {};
  const rawRef = pick(o, 'ref', 'refNo', 'ref_no', 'number', 'index');
  const rawChunkId = pick(o, 'chunkId', 'chunk_id', 'chunk', 'id');
  const chunkId = str(rawChunkId, '');

  // ref 可能是 1..k 的编号，也可能是 D02-C001 这种 ID
  let ref: number | string;
  if (typeof rawRef === 'number') {
    ref = rawRef;
  } else if (typeof rawRef === 'string' && rawRef.trim() !== '') {
    ref = CHUNK_ID_RE.test(rawRef.trim()) ? rawRef.trim() : num(rawRef, index + 1);
  } else if (CHUNK_ID_RE.test(chunkId)) {
    ref = chunkId;
  } else {
    ref = index + 1;
  }

  const docTitle = str(pick(o, 'docTitle', 'doc_title', 'source', 'fileName', 'file_name'));
  const docId = str(pick(o, 'docId', 'doc_id'), docTitle.slice(0, 2).toUpperCase());

  // chunkId 缺失但 ref 本身是片段 ID 时，两者视为同一个值（规格 §7.5 的写法）
  const resolvedChunkId = CHUNK_ID_RE.test(chunkId)
    ? chunkId
    : typeof ref === 'string' && CHUNK_ID_RE.test(ref)
      ? ref
      : chunkId;

  return {
    ref,
    chunkId: resolvedChunkId,
    docId,
    docTitle,
    headingPath: str(pick(o, 'headingPath', 'heading_path', 'heading')),
    text: str(pick(o, 'text', 'chunk', 'excerpt', 'content')),
    start: num(pick(o, 'start', 'startIndex', 'start_index')),
    end: num(pick(o, 'end', 'endIndex', 'end_index')),
    score: num(pick(o, 'score', 'similarity'), 0),
    stage: str(pick(o, 'stage'), 'rerank') || undefined,
    kind: normalizeKind(pick(o, 'kind', 'type')),
    verified: bool(pick(o, 'verified'), true),
  };
}

export function normalizeCitations(input: unknown): Citation[] {
  return arr<unknown>(input).map((item, i) => normalizeCitation(item, i));
}

export function normalizeTraceRow(input: unknown, index = 0): TraceRow {
  const o = isDict(input) ? input : {};
  const cite = normalizeCitation({ ...o, ref: pick(o, 'ref') ?? index + 1 }, index);
  return {
    rank: num(pick(o, 'rank', 'no', 'order'), index + 1),
    chunkId: cite.chunkId,
    docId: cite.docId,
    docTitle: cite.docTitle,
    headingPath: cite.headingPath,
    text: cite.text,
    start: cite.start,
    end: cite.end,
    score: cite.score,
    retrieved: bool(pick(o, 'retrieved'), index < 3),
    kind: cite.kind,
    verified: cite.verified,
  };
}

export function normalizeTrace(input: unknown): RetrievalTrace | null {
  if (!isDict(input)) return null;
  const rows = arr<unknown>(pick(input, 'rows', 'items', 'chunks', 'retrieved')).map((r, i) =>
    normalizeTraceRow(r, i),
  );
  if (rows.length === 0) return null;
  return {
    question: str(pick(input, 'question', 'query')),
    k: num(pick(input, 'k', 'topK', 'top_k'), 3),
    chunkSize: num(pick(input, 'chunkSize', 'chunk_size'), 180),
    overlap: num(pick(input, 'overlap', 'chunkOverlap', 'chunk_overlap'), 30),
    rows,
  };
}

export function normalizeMessage(input: unknown): Message {
  const o = isDict(input) ? input : {};
  return {
    id: str(pick(o, 'id', 'messageId', 'message_id'), `m-${Math.random().toString(36).slice(2)}`),
    conversationId: str(pick(o, 'conversationId', 'conversation_id', 'sessionId', 'session_id')),
    role: str(pick(o, 'role'), 'assistant') === 'user' ? 'user' : 'assistant',
    content: str(pick(o, 'content', 'answer', 'text')),
    createdAt: num(pick(o, 'createdAt', 'created_at'), Date.now()),
    citations: normalizeCitations(pick(o, 'citations', 'sources')),
    trace: normalizeTrace(pick(o, 'trace', 'retrievalTrace', 'retrieval_trace')),
    usage: isDict(pick(o, 'usage')) ? (pick(o, 'usage') as Record<string, number>) : null,
    elapsedMs: (() => {
      const v = pick(o, 'elapsedMs', 'elapsed_ms', 'elapsed');
      return v === undefined ? null : num(v);
    })(),
    degraded: bool(pick(o, 'degraded'), false),
    suggestions: arr<string>(pick(o, 'suggestions')).filter((s) => typeof s === 'string'),
    feedback: (() => {
      const v = str(pick(o, 'feedback'), '');
      return v === 'up' || v === 'down' ? v : null;
    })(),
    error: str(pick(o, 'error'), '') || null,
  };
}

export function normalizeMessages(input: unknown): Message[] {
  return arr<unknown>(input).map(normalizeMessage);
}

export function normalizeDocument(input: unknown): DocumentMeta {
  const o = isDict(input) ? input : {};
  const name = str(pick(o, 'name', 'fileName', 'file_name', 'source'));
  return {
    id: str(pick(o, 'id', 'docId', 'doc_id'), name),
    name,
    title: str(pick(o, 'title'), name.replace(/\.(md|txt)$/i, '')),
    tags: arr<string>(pick(o, 'tags')).filter((t) => typeof t === 'string'),
    version: str(pick(o, 'version'), 'v1'),
    charCount: num(pick(o, 'charCount', 'char_count', 'chars', 'length')),
    chunkCount: num(pick(o, 'chunkCount', 'chunk_count', 'chunks')),
    status: (() => {
      const s = str(pick(o, 'status'), 'INDEXED').toUpperCase();
      const allowed = ['UPLOADING', 'PARSING', 'INDEXED', 'FAILED', 'NEEDS_REBUILD', 'DISABLED'];
      return (allowed.includes(s) ? s : 'INDEXED') as DocumentMeta['status'];
    })(),
    verified: bool(pick(o, 'verified'), name !== '06_成员留言摘录.md'),
    updatedAt: num(pick(o, 'updatedAt', 'updated_at'), Date.now()),
    error: str(pick(o, 'error'), '') || null,
  };
}

export function normalizeDocuments(input: unknown): DocumentMeta[] {
  return arr<unknown>(input).map(normalizeDocument);
}

export function normalizeIndexStatus(input: unknown): IndexStatus {
  const o = isDict(input) ? input : {};
  const raw = str(pick(o, 'status'), 'unavailable');
  const status: IndexStatus['status'] =
    raw === 'ready' || raw === 'needs_rebuild' ? raw : 'unavailable';
  const lastBuilt = pick(o, 'lastBuiltAt', 'last_built_at', 'builtAt');
  const manifest = pick(o, 'manifest');
  return {
    status,
    docCount: num(pick(o, 'docCount', 'doc_count')),
    chunkCount: num(pick(o, 'chunkCount', 'chunk_count', 'chunks')),
    chunkSize: num(pick(o, 'chunkSize', 'chunk_size'), 180),
    overlap: num(pick(o, 'overlap', 'chunkOverlap', 'chunk_overlap'), 30),
    embeddingModel: str(pick(o, 'embeddingModel', 'embedding_model'), 'unknown'),
    lastBuiltAt: lastBuilt === undefined || lastBuilt === null ? null : num(lastBuilt),
    reason: str(pick(o, 'reason'), '') || null,
    manifest: isDict(manifest) ? normalizeIndexManifest(manifest) : null,
  };
}

/** 清单快照：字段全可选，缺失就保持 undefined（不编造 0） */
function normalizeIndexManifest(o: Record<string, unknown>): IndexManifest {
  const opt = (value: unknown): number | undefined =>
    value === undefined || value === null || value === '' ? undefined : num(value);
  const model = str(pick(o, 'embeddingModel', 'embedding_model'), '');
  const sha = str(pick(o, 'sha256'), '');
  return {
    embeddingModel: model || undefined,
    chunkSize: opt(pick(o, 'chunkSize', 'chunk_size')),
    overlap: opt(pick(o, 'overlap')),
    docCount: opt(pick(o, 'docCount', 'doc_count')),
    chunkCount: opt(pick(o, 'chunkCount', 'chunk_count')),
    builtAt: opt(pick(o, 'builtAt', 'built_at')),
    sha256: sha || undefined,
  };
}
