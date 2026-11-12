import type {
  ChunkItem,
  ChunkQuery,
  DocumentMeta,
  IndexStatus,
  IndexTask,
  RebuildRequest,
  UploadResult,
} from '@/types/api';
import { del, get, post, put, upload } from '../http';
import { normalizeDocument, normalizeDocuments, normalizeIndexStatus } from '../normalize';

/* ---------------------------------------------------------------- 资料 */

export async function listDocuments(): Promise<DocumentMeta[]> {
  const raw = await get<unknown>('/documents');
  const items = Array.isArray(raw) ? raw : ((raw as { items?: unknown[] })?.items ?? []);
  return normalizeDocuments(items);
}

/** 上传：字段名必须是 files（多选） */
export async function uploadDocuments(files: File[]): Promise<UploadResult> {
  const form = new FormData();
  for (const file of files) form.append('files', file, file.name);
  const raw = (await upload<unknown>('/documents', form)) ?? {};
  const o = raw as { accepted?: unknown[]; skipped?: unknown[] };
  return {
    accepted: normalizeDocuments(o.accepted ?? []),
    skipped: (Array.isArray(o.skipped) ? o.skipped : []).map((s) => {
      const item = (s ?? {}) as Record<string, unknown>;
      return { name: String(item.name ?? ''), reason: String(item.reason ?? '') };
    }),
  };
}

export async function updateDocument(
  id: string,
  patch: Partial<Pick<DocumentMeta, 'title' | 'tags' | 'version' | 'status'>>,
): Promise<DocumentMeta> {
  const raw = await put<unknown>(`/documents/${encodeURIComponent(id)}`, patch);
  return normalizeDocument(raw);
}

export async function deleteDocument(id: string): Promise<void> {
  await del<void>(`/documents/${encodeURIComponent(id)}`);
}

/** 启停用（DISABLED / INDEXED） */
export async function setDocumentEnabled(id: string, enabled: boolean): Promise<DocumentMeta> {
  return updateDocument(id, { status: enabled ? 'INDEXED' : 'DISABLED' });
}

/* ---------------------------------------------------------------- 建库 */

export async function fetchIndexStatus(): Promise<IndexStatus> {
  const raw = await get<unknown>('/index/status');
  return normalizeIndexStatus(raw);
}

export async function rebuildIndex(payload: RebuildRequest): Promise<IndexTask> {
  const raw = (await post<unknown>('/index/rebuild', payload)) ?? {};
  return normalizeTask(raw);
}

export async function fetchIndexTask(id: string): Promise<IndexTask> {
  const raw = await get<unknown>(`/index/tasks/${encodeURIComponent(id)}`);
  return normalizeTask(raw);
}

function normalizeTask(raw: unknown): IndexTask {
  const o = (raw ?? {}) as Record<string, unknown>;
  const status = String(o.status ?? 'RUNNING').toUpperCase();
  const stage = String(o.stage ?? 'parsing').toLowerCase();
  return {
    id: String(o.id ?? o.taskId ?? ''),
    status: (['PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED'].includes(status)
      ? status
      : 'RUNNING') as IndexTask['status'],
    stage: (['parsing', 'splitting', 'embedding', 'summarizing', 'done'].includes(stage)
      ? stage
      : 'parsing') as IndexTask['stage'],
    progress: Number(o.progress ?? 0),
    chunkSize: Number(o.chunkSize ?? o.chunk_size ?? 0),
    overlap: Number(o.overlap ?? o.chunk_overlap ?? 0),
    docCount: Number(o.docCount ?? o.doc_count ?? 0),
    chunkCount: Number(o.chunkCount ?? o.chunk_count ?? 0),
    error: (o.error as string | null) ?? null,
    startedAt: Number(o.startedAt ?? o.started_at ?? Date.now()),
    finishedAt: o.finishedAt ? Number(o.finishedAt) : null,
  };
}

/* ---------------------------------------------------------------- 片段 */

export async function listChunks(query: ChunkQuery = {}): Promise<ChunkItem[]> {
  const raw = await get<unknown>('/chunks', { params: query });
  const items = Array.isArray(raw) ? raw : ((raw as { items?: unknown[] })?.items ?? []);
  return items.map((item, i) => {
    const o = (item ?? {}) as Record<string, unknown>;
    return {
      chunkId: String(o.chunkId ?? o.chunk_id ?? `C${i + 1}`),
      docId: String(o.docId ?? o.doc_id ?? ''),
      docTitle: String(o.docTitle ?? o.doc_title ?? o.source ?? ''),
      headingPath: String(o.headingPath ?? o.heading_path ?? ''),
      text: String(o.text ?? o.content ?? ''),
      start: Number(o.start ?? 0),
      end: Number(o.end ?? 0),
      kind: (['chunk', 'summary', 'rule'].includes(String(o.kind)) ? o.kind : 'chunk') as ChunkItem['kind'],
      verified: o.verified !== false,
      index: Number(o.index ?? i),
    } satisfies ChunkItem;
  });
}
