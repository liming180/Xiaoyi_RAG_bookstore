<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import type { ChunkItem, CitationKind } from '@/types/api';
import ChunkCard from '../components/ChunkCard.vue';
import HeadingTree from '../components/HeadingTree.vue';
import OverlapPanel from '../components/OverlapPanel.vue';
import { useChunks } from '../composables/useChunks';

/**
 * ChunksView —— 片段浏览（P4-B，覆盖拓展 B + F05 跳转定位）。
 *
 * 三块信息架构：
 *  左栏：文档分组（选了文档才能收敛标题树）+ 标题树 + 类型过滤
 *  右栏：筛选条（关键词）+ 片段列表
 *  顶部：从引用卡跳进来时的定位条 + 相邻片段并排开关
 *
 * 定位链路：引用卡点「在知识库中查看」→ 路由 query 带 chunk_id
 *          → 本页挂载后按 chunk_id 找到片段 → 滚动 + 高亮描边。
 */
const route = useRoute();
const router = useRouter();

const initialChunkId = typeof route.query.chunk_id === 'string' ? route.query.chunk_id : null;
const initialDocTitle = typeof route.query.doc === 'string' ? route.query.doc : null;

const chunks = useChunks({ focusChunkId: initialChunkId });
const listRef = ref<HTMLElement | null>(null);

const KIND_OPTIONS: Array<{ value: CitationKind; label: string }> = [
  { value: 'chunk', label: '正文片段' },
  { value: 'summary', label: '全局汇总' },
  { value: 'rule', label: '规则条目' },
];

const activeHeading = computed(() => chunks.heading.value);
const focusedChunk = computed(() => chunks.focused.value);
const neighborhood = computed(() => chunks.neighborhood.value);

onMounted(async () => {
  await chunks.load();
  if (initialChunkId) {
    await scrollToFocused();
  }
});

/** 滚到定位片段并高亮（引用卡跳转的落点） */
async function scrollToFocused(): Promise<void> {
  await nextTick();
  const target = document.querySelector(
    `[data-testid="chunk-card-${initialChunkId ?? chunks.focusId.value ?? ''}"]`,
  );
  target?.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

async function onFocus(chunk: ChunkItem): Promise<void> {
  chunks.focus(chunk.chunkId);
  chunks.setCompare(true);
  await nextTick();
  document
    .querySelector(`[data-testid="chunk-card-${chunk.chunkId}"]`)
    ?.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

function onCloseCompare(): void {
  chunks.setCompare(false);
}

async function onCopy(chunk: ChunkItem): Promise<void> {
  try {
    await navigator.clipboard.writeText(chunk.text);
    ElMessage.success(`已复制 ${chunk.chunkId}`);
  } catch {
    ElMessage.warning('复制失败，请手动选择文本');
  }
}

function onDocChange(next: string | null): void {
  chunks.setDoc(next);
}

function onHeadingChange(next: string | null): void {
  chunks.setHeading(next);
}

function onKindChange(next: CitationKind | null): void {
  chunks.setKind(next);
}

function clearAll(): void {
  chunks.resetFilters();
  chunks.focus(null);
  void router.replace({ name: 'chunks' });
}

/** 路由 query 变化（同一页面再次从引用卡跳进来）时重新定位 */
watch(
  () => route.query.chunk_id,
  (next) => {
    if (typeof next !== 'string' || !next) return;
    chunks.focus(next);
    void scrollToFocused();
  },
);
</script>

<template>
  <section class="chunks" data-testid="page-chunks">
    <header class="chunks__head">
      <div>
        <h1 class="chunks__title">片段浏览</h1>
        <p class="chunks__sub" data-testid="chunk-count">
          共 {{ chunks.all.value.length }} 条片段 · 当前显示 {{ chunks.items.value.length }} 条
        </p>
      </div>
      <div class="chunks__actions">
        <el-button size="small" data-testid="chunks-back" @click="router.push({ name: 'knowledge' })">
          返回知识库
        </el-button>
        <el-button size="small" data-testid="chunks-clear" @click="clearAll">清除筛选</el-button>
      </div>
    </header>

    <!-- 从引用卡跳进来的定位提示条 -->
    <div v-if="focusedChunk" class="chunks__locator" data-testid="chunk-locator">
      <span class="chunks__locator-label">已定位</span>
      <code class="chunks__locator-id">{{ focusedChunk.chunkId }}</code>
      <span class="chunks__locator-doc">
        {{ focusedChunk.docTitle }}<template v-if="initialDocTitle"> · 来自引用卡</template>
      </span>
      <el-button
        size="small"
        text
        data-testid="chunk-locator-reset"
        @click="chunks.focus(null)"
      >
        取消定位
      </el-button>
    </div>

    <div class="chunks__body">
      <!-- 左栏：文档分组 + 标题树 + 类型 -->
      <aside class="chunks__side" data-testid="chunk-side">
        <section class="chunks__block">
          <h2 class="chunks__block-title">按资料</h2>
          <button
            type="button"
            class="chunks__doc"
            :class="{ 'chunks__doc--on': !chunks.docId.value }"
            data-testid="doc-filter-all"
            @click="onDocChange(null)"
          >
            <span class="chunks__doc-name">全部资料</span>
            <span class="chunks__doc-count">{{ chunks.all.value.length }}</span>
          </button>
          <button
            v-for="group in chunks.groups.value"
            :key="group.docId"
            type="button"
            class="chunks__doc"
            :class="{ 'chunks__doc--on': chunks.docId.value === group.docId }"
            :data-testid="`doc-filter-${group.docId}`"
            @click="onDocChange(group.docId)"
          >
            <span class="chunks__doc-name">{{ group.docTitle }}</span>
            <span class="chunks__doc-count">{{ group.count }}</span>
          </button>
        </section>

        <section class="chunks__block">
          <h2 class="chunks__block-title">按章节</h2>
          <HeadingTree
            :nodes="chunks.tree.value"
            :selected="activeHeading"
            @select="onHeadingChange"
          />
        </section>

        <section class="chunks__block">
          <h2 class="chunks__block-title">按类型</h2>
          <div class="chunks__kinds">
            <button
              type="button"
              class="chunks__kind"
              :class="{ 'chunks__kind--on': !chunks.kind.value }"
              data-testid="kind-all"
              @click="onKindChange(null)"
            >
              全部
            </button>
            <button
              v-for="option in KIND_OPTIONS"
              :key="option.value"
              type="button"
              class="chunks__kind"
              :class="{ 'chunks__kind--on': chunks.kind.value === option.value }"
              :data-testid="`kind-${option.value}`"
              @click="onKindChange(option.value)"
            >
              {{ option.label }}
            </button>
          </div>
        </section>
      </aside>

      <!-- 右栏：筛选条 + 片段列表 -->
      <main class="chunks__main">
        <div class="chunks__bar">
          <el-input
            :model-value="chunks.keyword.value"
            size="small"
            clearable
            placeholder="关键词过滤，例如：续借"
            data-testid="chunk-keyword"
            @update:model-value="(v: string) => chunks.setKeyword(v)"
          />
          <el-switch
            :model-value="chunks.compare.value"
            size="small"
            active-text="相邻并排"
            data-testid="compare-switch"
            @update:model-value="(v: string | number | boolean) => chunks.setCompare(Boolean(v))"
          />
        </div>

        <!-- 相邻片段并排（观察 overlap） -->
        <OverlapPanel
          v-if="neighborhood"
          :prev="neighborhood.prev"
          :self="neighborhood.self"
          :next="neighborhood.next"
          @close="onCloseCompare"
        />

        <div v-if="chunks.loading.value" class="chunks__state" data-testid="chunks-loading">
          正在加载片段…
        </div>
        <div
          v-else-if="chunks.error.value"
          class="chunks__state chunks__state--error"
          data-testid="chunks-error"
        >
          {{ chunks.error.value }}
        </div>
        <div
          v-else-if="chunks.items.value.length === 0"
          class="chunks__state"
          data-testid="chunks-empty"
        >
          <template v-if="chunks.hasFilters.value">没有匹配的片段，试试放宽筛选条件。</template>
          <template v-else>知识库还没有片段，先在知识库页上传资料并建库。</template>
        </div>

        <div v-else ref="listRef" class="chunks__list" data-testid="chunk-list">
          <ChunkCard
            v-for="chunk in chunks.items.value"
            :key="chunk.chunkId"
            :chunk="chunk"
            :keyword="chunks.keyword.value"
            :focused="chunks.focusId.value === chunk.chunkId"
            @focus="onFocus"
            @copy="onCopy"
          />
        </div>
      </main>
    </div>
  </section>
</template>

<style scoped>
.chunks {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px 22px 28px;
  max-width: 1180px;
}

.chunks__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.chunks__title {
  margin: 0;
  font-size: 18px;
}

.chunks__sub {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--muted);
}

.chunks__actions {
  display: flex;
  gap: 8px;
}

.chunks__locator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  font-size: 12px;
  background: var(--soft);
  border: 1px solid var(--teal);
  border-radius: var(--radius-sm);
}

.chunks__locator-label {
  color: var(--teal-dark);
  font-weight: 600;
}

.chunks__locator-id {
  font-family: var(--font-mono);
  color: var(--teal-dark);
}

.chunks__locator-doc {
  color: var(--muted);
}

.chunks__body {
  display: grid;
  grid-template-columns: 232px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}

@media (max-width: 900px) {
  .chunks__body {
    grid-template-columns: 1fr;
  }
}

.chunks__side {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 10px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  position: sticky;
  top: 12px;
  max-height: calc(100vh - 120px);
  overflow: auto;
}

.chunks__block-title {
  margin: 0 0 4px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--muted);
  text-transform: uppercase;
}

.chunks__doc {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 4px 8px;
  font-size: 12px;
  color: var(--ink);
  background: transparent;
  border: 0;
  border-radius: var(--radius-sm);
  cursor: pointer;
  text-align: left;
}

.chunks__doc:hover {
  background: var(--soft);
}

.chunks__doc--on {
  color: var(--teal-dark);
  background: var(--soft);
  font-weight: 600;
}

.chunks__doc-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chunks__doc-count {
  flex: none;
  margin-left: 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--muted);
}

.chunks__kinds {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.chunks__kind {
  padding: 3px 9px;
  font-size: 11px;
  color: var(--muted);
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 999px;
  cursor: pointer;
}

.chunks__kind--on {
  color: var(--teal-dark);
  background: var(--soft);
  border-color: var(--teal);
}

.chunks__main {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.chunks__bar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.chunks__state {
  padding: 40px 20px;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.chunks__state--error {
  color: var(--red);
}

.chunks__list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
</style>
