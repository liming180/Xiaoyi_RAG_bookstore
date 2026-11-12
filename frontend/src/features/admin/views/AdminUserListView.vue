<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Plus, Refresh, Search } from '@element-plus/icons-vue';
import { ApiError, adminApi } from '@/api';
import type { AdminUserItem } from '@/types/api';
import AdminUserFormDialog from './AdminUserFormDialog.vue';

/**
 * 管理端 · 用户管理（06 号设计方案 §8）。
 *
 * 一屏内完成全部账号操作：搜索 → 分页列表 → 新建/编辑/重置密码/删除。
 * admin 那一行是只读的：不显示操作按钮，也不允许被删/被改 —— 唯一管理员自锁了就没人能救。
 */
const loading = ref(false);
const rows = ref<AdminUserItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const keyword = ref('');

const dialogOpen = ref(false);
const editing = ref<AdminUserItem | null>(null);

const passwordDialogOpen = ref(false);
const passwordTarget = ref<AdminUserItem | null>(null);
const newPassword = ref('');
const passwordSubmitting = ref(false);

const hasRows = computed(() => rows.value.length > 0);

function displayOf(row: AdminUserItem): string {
  return row.displayName && row.displayName.trim() ? row.displayName : row.username;
}

function formatTime(seconds: number): string {
  const date = new Date(seconds * 1000);
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const result = await adminApi.listUsers({
      page: page.value,
      size: size.value,
      keyword: keyword.value.trim() || undefined,
    });
    rows.value = result?.items ?? [];
    total.value = result?.total ?? 0;
  } catch (e) {
    const apiError = e instanceof ApiError ? e : null;
    ElMessage.error(apiError?.message ?? '加载用户列表失败');
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
  keyword.value = '';
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

function onCreate(): void {
  editing.value = null;
  dialogOpen.value = true;
}

function onEdit(row: AdminUserItem): void {
  editing.value = row;
  dialogOpen.value = true;
}

function onResetPassword(row: AdminUserItem): void {
  passwordTarget.value = row;
  newPassword.value = '';
  passwordDialogOpen.value = true;
}

async function submitPassword(): Promise<void> {
  const target = passwordTarget.value;
  if (!target || passwordSubmitting.value) return;

  const bytes = new TextEncoder().encode(newPassword.value).length;
  if (bytes < 12 || bytes > 72) {
    ElMessage.error('密码需为 12-72 个字节（中文 1 字按 3 字节计）');
    return;
  }

  passwordSubmitting.value = true;
  try {
    await adminApi.resetUserPassword(target.id, { newPassword: newPassword.value });
    ElMessage.success('密码已重置');
    passwordDialogOpen.value = false;
    void load();
  } catch (e) {
    const apiError = e instanceof ApiError ? e : null;
    ElMessage.error(apiError?.message ?? '重置密码失败');
  } finally {
    passwordSubmitting.value = false;
  }
}

async function onDelete(row: AdminUserItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除用户「${displayOf(row)}」？删除后该账号立即无法登录，历史数据保留。`,
      '删除用户',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    );
  } catch {
    return; // 用户取消
  }

  try {
    await adminApi.deleteUser(row.id);
    ElMessage.success('已删除');
    // 删掉当前页最后一条时回退一页，否则会停在空页上
    if (rows.value.length === 1 && page.value > 1) page.value -= 1;
    void load();
  } catch (e) {
    const apiError = e instanceof ApiError ? e : null;
    ElMessage.error(apiError?.message ?? '删除失败');
    void load();
  }
}

onMounted(() => {
  void load();
});
</script>

<template>
  <section class="user-admin" data-testid="page-admin-users">
    <div class="user-admin__toolbar">
      <el-input
        v-model="keyword"
        class="user-admin__search"
        placeholder="搜索用户名或显示名"
        clearable
        :prefix-icon="Search"
        data-testid="admin-user-search"
        @keyup.enter="onSearch"
        @clear="onReset"
      />
      <el-button :icon="Search" data-testid="admin-user-search-submit" @click="onSearch">
        搜索
      </el-button>
      <el-button :icon="Refresh" data-testid="admin-user-reset" @click="onReset">重置</el-button>
      <div class="user-admin__spacer" />
      <el-button
        type="primary"
        :icon="Plus"
        data-testid="admin-user-create"
        @click="onCreate"
      >
        新建用户
      </el-button>
    </div>

    <el-table
      v-loading="loading"
      :data="rows"
      class="user-admin__table"
      data-testid="admin-user-table"
      empty-text="没有匹配的用户"
    >
      <el-table-column prop="id" label="ID" width="72" />
      <el-table-column prop="username" label="用户名" min-width="140" />
      <el-table-column label="显示名" min-width="140">
        <template #default="{ row }">{{ displayOf(row) }}</template>
      </el-table-column>
      <el-table-column label="角色" width="110">
        <template #default="{ row }">
          <el-tag :type="row.role === 'ADMIN' ? 'danger' : 'primary'" size="small">
            {{ row.role }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="150">
        <template #default="{ row }">{{ formatTime(row.createdAt) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <!-- admin 行只读：唯一管理员不能改自己、不能删自己，否则系统锁死 -->
          <el-tag v-if="row.role === 'ADMIN'" size="small" type="info">当前管理员</el-tag>
          <template v-else>
            <el-button size="small" text data-testid="admin-user-edit" @click="onEdit(row)">
              编辑
            </el-button>
            <el-button
              size="small"
              text
              data-testid="admin-user-reset-password"
              @click="onResetPassword(row)"
            >
              重置密码
            </el-button>
            <el-button
              size="small"
              text
              type="danger"
              data-testid="admin-user-delete"
              @click="onDelete(row)"
            >
              删除
            </el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>

    <div class="user-admin__footer">
      <span class="user-admin__total" data-testid="admin-user-total">共 {{ total }} 条</span>
      <el-pagination
        :current-page="page"
        :page-size="size"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="sizes, prev, pager, next"
        background
        data-testid="admin-user-pagination"
        @update:current-page="onPageChange"
        @update:page-size="onSizeChange"
      />
    </div>

    <p v-if="!hasRows && !loading" class="user-admin__empty" />

    <AdminUserFormDialog v-model="dialogOpen" :target="editing" @saved="load" />

    <el-dialog
      v-model="passwordDialogOpen"
      title="重置密码"
      width="400px"
      data-testid="admin-password-dialog"
    >
      <p class="user-admin__reset-hint">
        为「{{ passwordTarget ? displayOf(passwordTarget) : '' }}」设置新密码。
      </p>
      <el-input
        v-model="newPassword"
        type="password"
        show-password
        placeholder="12-72 个字节"
        data-testid="admin-password-input"
      />
      <template #footer>
        <el-button data-testid="admin-password-cancel" @click="passwordDialogOpen = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="passwordSubmitting"
          data-testid="admin-password-submit"
          @click="submitPassword"
        >
          确定
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.user-admin {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.user-admin__toolbar {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.user-admin__search {
  max-width: 280px;
}

.user-admin__spacer {
  flex: 1;
}

.user-admin__table {
  background: var(--paper);
  border-radius: var(--radius-sm);
}

.user-admin__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
}

.user-admin__total {
  font-size: 12.5px;
  color: var(--muted);
}

.user-admin__reset-hint {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--text);
}

.user-admin__empty {
  display: none;
}
</style>
