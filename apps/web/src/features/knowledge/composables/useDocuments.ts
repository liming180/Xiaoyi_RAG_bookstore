import { computed, ref } from 'vue';
import { knowledgeApi } from '@/api';
import type { DocumentMeta, DocumentStatus, UploadResult } from '@/types/api';
import { splitFiles } from './uploadRules';

/**
 * 资料列表状态（F01）。
 *
 * 只做「这一页要用的」服务端数据：列表、加载态、错误、按状态分组统计。
 * 不放进 Pinia —— 资料列表是页面级数据，别的页面要的是状态灯（systemStatus store）。
 */
export function useDocuments() {
  const items = ref<DocumentMeta[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const uploading = ref(false);

  const total = computed(() => items.value.length);

  const totalChars = computed(() => items.value.reduce((sum, d) => sum + d.charCount, 0));

  const totalChunks = computed(() => items.value.reduce((sum, d) => sum + d.chunkCount, 0));

  const unverifiedCount = computed(() => items.value.filter((d) => !d.verified).length);

  const statusCount = computed<Record<DocumentStatus, number>>(() => {
    const base: Record<DocumentStatus, number> = {
      UPLOADING: 0,
      PARSING: 0,
      INDEXED: 0,
      FAILED: 0,
      NEEDS_REBUILD: 0,
      DISABLED: 0,
    };
    for (const doc of items.value) base[doc.status] += 1;
    return base;
  });

  async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      items.value = await knowledgeApi.listDocuments();
    } catch (e) {
      error.value = e instanceof Error ? e.message : '资料列表加载失败';
    } finally {
      loading.value = false;
    }
  }

  /**
   * 上传：前端先挡一层（扩展名/大小），被挡的与后端 skipped 合并成一份提示清单。
   * 返回 skipped 供页面弹提示，accepted 数量供判断是否需要刷新。
   */
  async function upload(files: File[]): Promise<UploadResult> {
    const { accepted, rejected } = splitFiles(files);
    if (accepted.length === 0) {
      return { accepted: [], skipped: rejected };
    }
    uploading.value = true;
    try {
      const result = await knowledgeApi.uploadDocuments(accepted);
      const merged: UploadResult = {
        accepted: result.accepted,
        skipped: [...rejected, ...result.skipped],
      };
      if (merged.accepted.length > 0) await load();
      return merged;
    } finally {
      uploading.value = false;
    }
  }

  /** 启停用：本地乐观更新，失败回滚 */
  async function setEnabled(id: string, enabled: boolean): Promise<void> {
    const target = items.value.find((d) => d.id === id);
    if (!target) return;
    const prev = target.status;
    target.status = enabled ? 'INDEXED' : 'DISABLED';
    try {
      const next = await knowledgeApi.setDocumentEnabled(id, enabled);
      Object.assign(target, next);
    } catch (e) {
      target.status = prev;
      throw e;
    }
  }

  async function remove(id: string): Promise<void> {
    await knowledgeApi.deleteDocument(id);
    items.value = items.value.filter((d) => d.id !== id);
  }

  return {
    items,
    loading,
    error,
    uploading,
    total,
    totalChars,
    totalChunks,
    unverifiedCount,
    statusCount,
    load,
    upload,
    setEnabled,
    remove,
  };
}
