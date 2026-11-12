<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { knowledgeApi } from '@/api';
import type { DocumentMeta, IndexTask } from '@/types/api';
import { useSystemStatusStore } from '@/stores/systemStatus';
import DocumentTable from '../components/DocumentTable.vue';
import UploadDialog from '../components/UploadDialog.vue';
import BuildPanel from '../components/BuildPanel.vue';
import { useDocuments } from '../composables/useDocuments';
import { useRebuild } from '../composables/useRebuild';
import { validateBuildParams } from '../composables/buildParams';

/**
 * KnowledgeView —— 知识库页（P4-A，覆盖 F01/F02/F03）。
 *
 * 页面职责：
 *  - 资料列表（六态徽标 / 启停用 / 删除 / 查看全文）
 *  - 上传（前端先校验 → 后端 → 列表刷新 → 状态灯变黄）
 *  - 建库（参数校验 → POST → 1s 轮询 → 进度与阶段 → 完成摘要）
 *
 * 状态联动：任何写操作后既刷新列表，也立刻把 F03 状态灯置黄（markNeedsRebuild），
 * 不等 30s 轮询 —— 这是 F02 验收「改参数未建库时状态灯变黄」的要求。
 */
const route = useRoute();
const router = useRouter();
const systemStatus = useSystemStatusStore();

const docs = useDocuments();
const rebuild = useRebuild();

const uploadOpen = ref(false);
const busyId = ref<string | null>(null);
const focusBuild = computed(() => route.query.focus === 'build');

const builtParams = computed(() => {
  const detail = systemStatus.detail;
  if (!detail) return null;
  return { chunkSize: detail.chunkSize, overlap: detail.overlap };
});

const buildTask = computed<IndexTask | null>(() => rebuild.task.value);

const counts = computed(() => docs.statusCount.value);

async function refreshAll(): Promise<void> {
  await Promise.all([docs.load(), systemStatus.refresh()]);
}

onMounted(() => {
  void refreshAll();
  if (focusBuild.value) {
    // 从横幅「重新建库」跳进来时，滚到建库面板
    requestAnimationFrame(() => {
      document.querySelector('[data-testid="build-panel"]')?.scrollIntoView({ block: 'center' });
    });
  }
});

/* ------------------------------------------------------------ 上传 */

function openUpload(): void {
  uploadOpen.value = true;
}

async function onUpload(files: File[]): Promise<void> {
  try {
    const result = await docs.upload(files);
    uploadOpen.value = false;

    if (result.accepted.length > 0) {
      systemStatus.markNeedsRebuild('资料已变更');
      ElMessage.success(`已上传 ${result.accepted.length} 份资料，请重新建库`);
    }
    if (result.skipped.length > 0) {
      const text = result.skipped.map((s) => `${s.name}：${s.reason}`).join('；');
      ElMessage.warning(`已跳过 ${result.skipped.length} 份 — ${text}`);
    }
    if (result.accepted.length === 0 && result.skipped.length === 0) {
      ElMessage.info('没有选择文件');
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '上传失败');
  }
}

/* ------------------------------------------------------------ 启停用 / 删除 */

async function onToggle(doc: DocumentMeta, enabled: boolean): Promise<void> {
  busyId.value = doc.id;
  try {
    await docs.setEnabled(doc.id, enabled);
    systemStatus.markNeedsRebuild(enabled ? `已启用 ${doc.name}` : `已停用 ${doc.name}`);
    ElMessage.success(enabled ? `已启用 ${doc.name}` : `已停用 ${doc.name}`);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败');
  } finally {
    busyId.value = null;
  }
}

async function onRemove(doc: DocumentMeta): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `删除后「${doc.name}」将从知识库移除，需要重新建库才会生效。`,
      '删除资料',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    );
  } catch {
    return; // 用户取消
  }

  busyId.value = doc.id;
  try {
    await docs.remove(doc.id);
    systemStatus.markNeedsRebuild(`已删除 ${doc.name}`);
    ElMessage.success(`已删除 ${doc.name}，请重新建库`);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '删除失败');
  } finally {
    busyId.value = null;
  }
}

/* ------------------------------------------------------------ 查看全文 */

const viewerOpen = ref(false);
const viewerDoc = ref<DocumentMeta | null>(null);
const viewerText = ref('');
const viewerLoading = ref(false);

async function onView(doc: DocumentMeta): Promise<void> {
  viewerDoc.value = doc;
  viewerOpen.value = true;
  viewerLoading.value = true;
  viewerText.value = '';
  try {
    const chunks = await knowledgeApi.listChunks({ docId: doc.id });
    const { mergeChunks } = await import('../composables/chunkMerge');
    const merged = mergeChunks(chunks);
    viewerText.value = merged.text || '（该资料还没有片段，重新建库后可查看全文）';
  } catch (e) {
    viewerText.value = e instanceof Error ? e.message : '全文加载失败';
  } finally {
    viewerLoading.value = false;
  }
}

/* ------------------------------------------------------------ 建库 */

async function onRebuild(params: { chunkSize: number; overlap: number }): Promise<void> {
  const invalid = validateBuildParams(params);
  if (invalid) {
    ElMessage.error(invalid);
    return;
  }

  const started = await rebuild.rebuild(params);
  if (!started) {
    ElMessage.error(rebuild.error.value ?? '建库请求失败');
    return;
  }

  systemStatus.markNeedsRebuild('正在重新建库');
}

/**
 * 任务终态后同步状态灯与列表。
 *
 * 用 watch 而不是 300ms 轮询：轮询会有 300ms 的窗口期，测试里表现为
 * 「摘要已经出现但状态灯还是黄的」，用户侧表现为状态灯慢半拍。
 */
watch(
  () => rebuild.running.value,
  (running, wasRunning) => {
    if (running || !wasRunning) return;
    if (rebuild.finished.value) {
      systemStatus.markReady(rebuild.task.value?.chunkCount);
      void docs.load();
      ElMessage.success('建库完成');
    } else if (rebuild.failed.value) {
      ElMessage.error(rebuild.task.value?.error ?? '建库失败');
    }
  },
);

function gotoChunks(): void {
  void router.push({ name: 'chunks' });
}
</script>

<template>
  <section class="knowledge" data-testid="page-knowledge">
    <header class="knowledge__head">
      <div class="knowledge__titles">
        <h1 class="knowledge__title">知识库</h1>
        <p class="knowledge__sub" data-testid="doc-count">
          {{ docs.total.value }} 份资料 · {{ docs.totalChunks.value }} 个片段 ·
          {{ docs.totalChars.value }} 字
        </p>
      </div>

      <div class="knowledge__actions">
        <el-button size="small" data-testid="goto-chunks" @click="gotoChunks">片段浏览</el-button>
        <el-button
          size="small"
          type="primary"
          data-testid="open-upload"
          @click="openUpload"
        >
          上传资料
        </el-button>
      </div>
    </header>

    <div class="knowledge__badges" data-testid="doc-status-summary">
      <span class="knowledge__badge">已入库 {{ counts.INDEXED }}</span>
      <span class="knowledge__badge knowledge__badge--warn">待重建 {{ counts.NEEDS_REBUILD }}</span>
      <span class="knowledge__badge">已停用 {{ counts.DISABLED }}</span>
      <span v-if="docs.unverifiedCount.value > 0" class="knowledge__badge knowledge__badge--warn">
        未核实 {{ docs.unverifiedCount.value }}
      </span>
    </div>

    <DocumentTable
      :documents="docs.items.value"
      :loading="docs.loading.value"
      :error="docs.error.value"
      :busy-id="busyId"
      @view="onView"
      @toggle="onToggle"
      @remove="onRemove"
    />

    <BuildPanel
      :built-params="builtParams"
      :task="buildTask"
      :running="rebuild.running.value"
      :error="rebuild.error.value"
      @rebuild="onRebuild"
    />

    <UploadDialog
      v-model="uploadOpen"
      :uploading="docs.uploading.value"
      @submit="onUpload"
    />

    <el-dialog
      v-model="viewerOpen"
      :title="viewerDoc?.name ?? '资料全文'"
      width="680px"
      data-testid="doc-viewer"
    >
      <div v-if="viewerLoading" class="knowledge__viewer-state">正在加载全文…</div>
      <pre v-else class="knowledge__viewer" data-testid="doc-viewer-text">{{ viewerText }}</pre>
    </el-dialog>
  </section>
</template>

<style scoped>
.knowledge {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px 22px 28px;
  max-width: 1180px;
}

.knowledge__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.knowledge__title {
  margin: 0;
  font-size: 18px;
}

.knowledge__sub {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--muted);
}

.knowledge__actions {
  display: flex;
  gap: 8px;
}

.knowledge__badges {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.knowledge__badge {
  padding: 1px 10px;
  font-size: 12px;
  color: var(--muted);
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 999px;
}

.knowledge__badge--warn {
  color: var(--amber);
  background: var(--amber-soft);
  border-color: var(--amber-soft);
}

.knowledge__viewer {
  margin: 0;
  max-height: 52vh;
  overflow: auto;
  padding: 12px;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--bg);
  border-radius: var(--radius-sm);
}

.knowledge__viewer-state {
  padding: 24px;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
}
</style>
