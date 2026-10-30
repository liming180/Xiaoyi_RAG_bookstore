<script setup lang="ts">
import { computed } from 'vue';
import type { DocumentMeta } from '@/types/api';
import StatusBadge from './StatusBadge.vue';

/**
 * DocumentTable —— 资料列表表格（F01）。
 *
 * 列：标题 / 标签 / 版本 / 字数 / 片段数 / 状态徽标 / 操作。
 * 未核实资料（06_成员留言摘录.md）额外挂琥珀「未核实」标记（配合 F11）。
 */
const props = defineProps<{
  documents: DocumentMeta[];
  loading?: boolean;
  error?: string | null;
  /** 正在提交启停用的文档 id，用于禁用该行按钮 */
  busyId?: string | null;
}>();

const emit = defineEmits<{
  view: [DocumentMeta];
  toggle: [DocumentMeta, boolean];
  remove: [DocumentMeta];
}>();

const rows = computed(() => props.documents);

function canToggle(doc: DocumentMeta): boolean {
  // 上传中/解析中的资料不允许启停用（状态由建库流程决定）
  return doc.status !== 'UPLOADING' && doc.status !== 'PARSING';
}

function isEnabled(doc: DocumentMeta): boolean {
  return doc.status !== 'DISABLED';
}

function onToggle(doc: DocumentMeta): void {
  emit('toggle', doc, !isEnabled(doc));
}

function onRemove(doc: DocumentMeta): void {
  emit('remove', doc);
}

function onView(doc: DocumentMeta): void {
  emit('view', doc);
}
</script>

<template>
  <div class="doc-table" data-testid="document-table">
    <div v-if="loading" class="doc-table__state" data-testid="doc-loading">正在加载资料…</div>

    <div
      v-else-if="error"
      class="doc-table__state doc-table__state--error"
      data-testid="doc-error"
    >
      {{ error }}
    </div>

    <div v-else-if="rows.length === 0" class="doc-table__state" data-testid="doc-empty">
      知识库还没有资料，先上传 .md / .txt 文件吧。
    </div>

    <table v-else class="doc-table__table">
      <thead>
        <tr>
          <th class="doc-table__col-title">标题</th>
          <th class="doc-table__col-tags">标签</th>
          <th class="doc-table__col-version">版本</th>
          <th class="doc-table__col-num">字数</th>
          <th class="doc-table__col-num">片段数</th>
          <th class="doc-table__col-status">状态</th>
          <th class="doc-table__col-actions">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="doc in rows"
          :key="doc.id"
          :data-testid="`doc-row-${doc.id}`"
          :data-status="doc.status"
        >
          <td class="doc-table__col-title">
            <button type="button" class="doc-table__name" @click="onView(doc)">
              {{ doc.title }}
            </button>
            <span class="doc-table__file">{{ doc.name }}</span>
            <span v-if="!doc.verified" class="badge badge--warn doc-table__unverified">
              未核实
            </span>
          </td>
          <td class="doc-table__col-tags">
            <span v-for="tag in doc.tags" :key="tag" class="doc-table__tag">{{ tag }}</span>
            <span v-if="doc.tags.length === 0" class="doc-table__none">—</span>
          </td>
          <td class="doc-table__col-version">
            <code>{{ doc.version }}</code>
          </td>
          <td class="doc-table__col-num">{{ doc.charCount }}</td>
          <td class="doc-table__col-num">{{ doc.chunkCount }}</td>
          <td class="doc-table__col-status">
            <StatusBadge :status="doc.status" />
          </td>
          <td class="doc-table__col-actions">
            <el-button
              size="small"
              text
              :disabled="!canToggle(doc) || busyId === doc.id"
              :data-testid="`doc-toggle-${doc.id}`"
              @click="onToggle(doc)"
            >
              {{ isEnabled(doc) ? '停用' : '启用' }}
            </el-button>
            <el-button
              size="small"
              text
              type="danger"
              :disabled="busyId === doc.id"
              :data-testid="`doc-delete-${doc.id}`"
              @click="onRemove(doc)"
            >
              删除
            </el-button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.doc-table {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
}

.doc-table__state {
  padding: 28px 20px;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
}

.doc-table__state--error {
  color: var(--red);
}

.doc-table__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.doc-table__table th {
  padding: 8px 12px;
  text-align: left;
  font-weight: 600;
  font-size: 12px;
  color: var(--muted);
  background: var(--bg);
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}

.doc-table__table td {
  padding: 10px 12px;
  vertical-align: middle;
  border-bottom: 1px solid var(--line);
}

.doc-table__table tbody tr:last-child td {
  border-bottom: 0;
}

.doc-table__table tbody tr:hover {
  background: color-mix(in srgb, var(--teal) 4%, transparent);
}

.doc-table__name {
  padding: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
  background: transparent;
  border: 0;
  cursor: pointer;
  text-align: left;
}

.doc-table__name:hover {
  color: var(--teal);
}

.doc-table__file {
  display: block;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--muted);
}

.doc-table__unverified {
  margin-left: 6px;
  transform: translateY(-1px);
}

.doc-table__col-tags {
  width: 150px;
}

.doc-table__tag {
  display: inline-block;
  margin-right: 4px;
  padding: 0 6px;
  font-size: 11px;
  color: var(--teal-dark);
  background: var(--soft);
  border-radius: 999px;
}

.doc-table__none {
  color: var(--muted);
}

.doc-table__col-version {
  width: 62px;
}

.doc-table__col-version code {
  font-size: 11px;
  color: var(--muted);
}

.doc-table__col-num {
  width: 74px;
  text-align: right;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--muted);
}

.doc-table__col-status {
  width: 88px;
}

.doc-table__col-actions {
  width: 132px;
  white-space: nowrap;
}
</style>
