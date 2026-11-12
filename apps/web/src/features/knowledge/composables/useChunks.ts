import { computed, ref } from 'vue';
import { knowledgeApi } from '@/api';
import type { ChunkItem, CitationKind } from '@/types/api';
import {
  buildDocGroups,
  buildHeadingTree,
  filterChunks,
  indexOfChunk,
  neighborhoodOf,
  type ChunkFilters,
} from './chunkFilter';

/**
 * useChunks —— 片段浏览的数据与筛选状态（P4-B）。
 *
 * 设计取舍：一次性拉全量片段后在本地过滤，而不是每改一个筛选条件就发一次请求。
 * 理由：知识库规模是本项目的固定语料（六份 md，约 40 条片段），
 * 本地过滤的响应是同步的，键入关键词时不会有网络抖动；
 * 同时让「按文档分组 / 标题树 / 关键词」三者可以任意组合而不产生请求风暴。
 */
export interface UseChunksOptions {
  /** 初始定位的片段 ID（来自对话引用卡跳转的 ?chunk_id=） */
  focusChunkId?: string | null;
}

export function useChunks(options: UseChunksOptions = {}) {
  const all = ref<ChunkItem[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);

  const docId = ref<string | null>(null);
  const heading = ref<string | null>(null);
  const keyword = ref('');
  const kind = ref<CitationKind | null>(null);
  /** 相邻片段并排观察 overlap */
  const compare = ref(false);
  const focusId = ref<string | null>(options.focusChunkId ?? null);

  async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      all.value = await knowledgeApi.listChunks();
    } catch (e) {
      error.value = e instanceof Error ? e.message : '片段加载失败';
      all.value = [];
    } finally {
      loading.value = false;
    }
  }

  const filters = computed<ChunkFilters>(() => ({
    docId: docId.value,
    heading: heading.value,
    keyword: keyword.value,
    kind: kind.value,
  }));

  /** 文档分组始终基于全量 —— 左栏要展示「有哪些资料」 */
  const groups = computed(() => buildDocGroups(all.value));

  /**
   * 标题树跟随文档筛选：选了某份资料就只长那棵树的枝。
   * 否则会出现「选 D01 + 选 D02 的章节 = 空结果」这种自相矛盾的组合。
   */
  const tree = computed(() => {
    const scope = docId.value ? all.value.filter((c) => c.docId === docId.value) : all.value;
    return buildHeadingTree(scope);
  });

  /** 筛选后的片段（列表主体） */
  const items = computed(() => filterChunks(all.value, filters.value));

  /** 当前定位的片段 */
  const focused = computed<ChunkItem | null>(() => {
    if (!focusId.value) return null;
    const at = indexOfChunk(all.value, focusId.value);
    return at >= 0 ? (all.value[at] ?? null) : null;
  });

  /** 相邻三件套（并排观察用） */
  const neighborhood = computed(() => {
    if (!compare.value || !focusId.value) return null;
    return neighborhoodOf(all.value, focusId.value);
  });

  const kindOptions = computed(() => {
    const set = new Set<CitationKind>();
    for (const chunk of all.value) set.add(chunk.kind);
    return [...set].sort();
  });

  const hasFilters = computed(
    () => Boolean(docId.value || heading.value || keyword.value.trim() || kind.value),
  );

  function setDoc(next: string | null): void {
    docId.value = next;
    // 换文档时清掉标题选择，避免「D01 的章节 + D02 的文档」这种空结果
    heading.value = null;
  }

  function setHeading(next: string | null): void {
    heading.value = next;
  }

  function setKeyword(next: string): void {
    keyword.value = next;
  }

  function setKind(next: CitationKind | null): void {
    kind.value = next;
  }

  function toggleCompare(): void {
    compare.value = !compare.value;
  }

  function setCompare(next: boolean): void {
    compare.value = next;
  }

  function focus(chunkId: string | null): void {
    focusId.value = chunkId;
  }

  function resetFilters(): void {
    docId.value = null;
    heading.value = null;
    keyword.value = '';
    kind.value = null;
  }

  return {
    all,
    items,
    groups,
    tree,
    kindOptions,
    loading,
    error,
    docId,
    heading,
    keyword,
    kind,
    compare,
    focusId,
    focused,
    neighborhood,
    hasFilters,
    load,
    setDoc,
    setHeading,
    setKeyword,
    setKind,
    toggleCompare,
    setCompare,
    focus,
    resetFilters,
  };
}
