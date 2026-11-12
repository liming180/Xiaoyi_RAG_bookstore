<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { Refresh, Search } from '@element-plus/icons-vue';
import { ApiError, adminApi } from '@/api';
import type { AdminAuditItem } from '@/types/api';

/**
 * 管理端 · 审计日志（只读）。
 *
 * 三个筛选维度对应后端的三条参数：动作（精确）、操作者 id（精确）、对象（target 包含）。
 * 页面上**没有**任何写操作按钮 —— 审计是账本，能改就没意义了。
 *
 * 为什么动作下拉从接口拉而不是硬编码：动作名是后端 `audit_log.action` 的实际取值，
 * 新增业务动作时下拉自动出现，前后端不会因为「页面里少写了一项」而漏筛。
 */
const loading = ref(false);
const rows = ref<AdminAuditItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);

const actionFilter = ref('');
const operatorFilter = ref('');
const targetFilter = ref('');

const actionOptions = ref<string[]>([]);

const hasRows = computed(() => rows.value.length > 0);

/** 动作名的中文说明。没登记的动作直接显示原文（不隐藏，避免「看不懂就当没发生」）。 */
const ACTION_LABELS: Record<string, string> = {
  'admin.user.create': '新建用户',
  'admin.user.update': '编辑用户',
  'admin.user.reset-password': '重置密码',
  'admin.user.delete': '删除用户',
};

function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action;
}

function formatTime(seconds: number): string {
  const date = new Date(seconds * 1000);
  const pad = (n: number): string => String(n).padStart(2, '0');
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  );
}

/**
 * detail_json 的展示。
 *
 * 后端存的是 JSON 文本；这里只在能解析时做缩进（便于阅读），解析失败就原样显示 ——
 * 审计详情是历史快照，不能因为格式不合当下预期就把它藏起来。
 */
function formatDetail(detail: string | null): string {
  if (!detail) return '—';
  try {
    return JSON.stringify(JSON.parse(detail), null, 2);
  } catch {
    return detail;
  }
}

async function loadActions(): Promise<void> {
  try {
    actionOptions.value = await adminApi.listAuditActions();
  } catch {
    // 下拉拉不到不该阻断列表：把筛选降级成「不过滤」即可
    actionOptions.value = [];
  }
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const operatorRaw = operatorFilter.value.trim();
    const operatorId = operatorRaw ? Number(operatorRaw) : undefined;
    // 非数字的操作者 id 不发给后端（后端会回 400）：直接提示，避免一次无意义的往返
    if (operatorRaw && (!Number.isFinite(operatorId) || (operatorId as number) <= 0)) {
      ElMessage.warning('操作者 ID 需为正整数');
      loading.value = false;
      return;
    }

    const result = await adminApi.listAuditLogs({
      page: page.value,
      size: size.value,
      action: actionFilter.value || undefined,
      operatorId,
      keyword: targetFilter.value.trim() || undefined,
    });
    rows.value = result?.items ?? [];
    total.value = result?.total ?? 0;
  } catch (e) {
    const apiError = e instanceof ApiError ? e : null;
    ElMessage.error(apiError?.message ?? '加载审计日志失败');
    rows.value = [];
    total.value = 0;
  } finally {
    loading.value = false;
  }
}

function onSearch(): void {
  page.value = 1;
  void load();
}

function onReset(): void {
  actionFilter.value = '';
  operatorFilter.value = '';
  targetFilter.value = '';
  page.value = 1;
  void load();
}

function onPageChange(next: number): void {
  page.value = next;
  void load();
}

function onSizeChange(next: number): void {
  size.value = next;
  page.value = 1;
  void load();
}

onMounted(() => {
  void loadActions();
  void load();
});
</script>

<template>
  <section class="audit" data-testid="page-admin-audit">
    <div class="audit__toolbar">
      <el-select
        v-model="actionFilter"
        class="audit__action"
        placeholder="全部动作"
        clearable
        data-testid="audit-action-filter"
        @change="onSearch"
      >
        <el-option
          v-for="action in actionOptions"
          :key="action"
          :label="actionLabel(action)"
          :value="action"
        />
      </el-select>

      <el-input
        v-model="operatorFilter"
        class="audit__operator"
        placeholder="操作者 ID"
        clearable
        data-testid="audit-operator-filter"
        @keyup.enter="onSearch"
        @clear="onSearch"
      />

      <el-input
        v-model="targetFilter"
        class="audit__target"
        placeholder="操作对象（如 user:7）"
        clearable
        data-testid="audit-target-filter"
        @keyup.enter="onSearch"
        @clear="onSearch"
      />

      <el-button :icon="Search" data-testid="audit-search" @click="onSearch">查询</el-button>
      <el-button :icon="Refresh" data-testid="audit-reset" @click="onReset">重置</el-button>
    </div>

    <el-table
      v-loading="loading"
      :data="rows"
      class="audit__table"
      data-testid="audit-table"
      empty-text="暂无审计记录"
    >
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column label="时间" width="170">
        <template #default="{ row }">{{ formatTime(row.createdAt) }}</template>
      </el-table-column>
      <el-table-column label="操作者" width="150">
        <template #default="{ row }">
          <span v-if="row.operatorName">{{ row.operatorName }}</span>
          <span v-else class="audit__missing">#{{ row.operatorId ?? '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="动作" width="150">
        <template #default="{ row }">
          <el-tag size="small" :type="row.action.endsWith('delete') ? 'danger' : 'primary'">
            {{ actionLabel(row.action) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="对象" width="130">
        <template #default="{ row }">{{ row.target ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="详情" min-width="220">
        <template #default="{ row }">
          <el-popover placement="left" :width="320" trigger="click">
            <template #reference>
              <el-button size="small" text data-testid="audit-detail-toggle">查看</el-button>
            </template>
            <pre class="audit__detail" data-testid="audit-detail-json">{{ formatDetail(row.detailJson) }}</pre>
          </el-popover>
        </template>
      </el-table-column>
    </el-table>

    <div class="audit__footer">
      <span class="audit__total" data-testid="audit-total">共 {{ total }} 条</span>
      <el-pagination
        :current-page="page"
        :page-size="size"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="sizes, prev, pager, next"
        background
        data-testid="audit-pagination"
        @update:current-page="onPageChange"
        @update:page-size="onSizeChange"
      />
    </div>

    <p v-if="!hasRows && !loading" class="audit__empty-hint">
      审计日志只读：记录管理端对账号的每一次增、改、删与重置密码。
    </p>
  </section>
</template>

<style scoped>
.audit {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.audit__toolbar {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}

.audit__action {
  width: 180px;
}

.audit__operator {
  width: 140px;
}

.audit__target {
  width: 200px;
}

.audit__table {
  background: var(--paper);
  border-radius: var(--radius-sm);
}

.audit__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
}

.audit__total {
  font-size: 12.5px;
  color: var(--muted);
}

.audit__missing {
  color: var(--muted);
  font-family: var(--mono, monospace);
  font-size: 12px;
}

.audit__detail {
  margin: 0;
  max-height: 240px;
  overflow: auto;
  font-family: var(--mono, monospace);
  font-size: 12px;
  line-height: 1.6;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-all;
}

.audit__empty-hint {
  margin: 0;
  font-size: 12.5px;
  color: var(--muted);
}
</style>
