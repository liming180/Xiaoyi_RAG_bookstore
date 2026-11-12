import type {
  AdminAuditPage,
  AdminUserCreateRequest,
  AdminUserItem,
  AdminUserPage,
  AdminUserPasswordRequest,
  AdminUserUpdateRequest,
} from '@/types/api';
import { del, get, post, put } from '../http';

/**
 * 管理端 API：用户管理（06 号方案 §5.2）+ 审计日志查询。
 *
 * 整组接口要求当前 token 的角色是 ADMIN：非管理员会收到 HTTP 403 / 40101。
 * 403 不会触发自动登出（只有 401 会），所以普通用户误入时只是「无权访问」，会话不受影响。
 */

/** 分页列表。keyword 为空表示不过滤。 */
export async function listUsers(params: {
  page?: number;
  size?: number;
  keyword?: string;
  includeDeleted?: boolean;
}): Promise<AdminUserPage> {
  return get<AdminUserPage>('/admin/users', { params });
}

/** 新建用户。服务端强制 role=USER —— 这个接口造不出第二个管理员。 */
export async function createUser(payload: AdminUserCreateRequest): Promise<AdminUserItem> {
  return post<AdminUserItem>('/admin/users', payload);
}

/** 改显示名（不含密码）。 */
export async function updateUser(
  id: number,
  payload: AdminUserUpdateRequest,
): Promise<AdminUserItem> {
  return put<AdminUserItem>(`/admin/users/${id}`, payload);
}

/** 重置密码。独立端点，独立审计动作。 */
export async function resetUserPassword(
  id: number,
  payload: AdminUserPasswordRequest,
): Promise<AdminUserItem> {
  return put<AdminUserItem>(`/admin/users/${id}/password`, payload);
}

/** 删除用户（软删）。删后立即不能登录，历史数据保留。 */
export async function deleteUser(id: number): Promise<void> {
  return del<void>(`/admin/users/${id}`);
}

/* ------------------------------------------------------------ 审计日志 */

/**
 * 审计日志分页查询（只读）。
 *
 * 三个过滤条件都可省略：action 精确匹配、operatorId 精确匹配、keyword 对 target 做包含匹配。
 * 服务端按 id 倒序（最新在前）。
 */
export async function listAuditLogs(params: {
  page?: number;
  size?: number;
  action?: string;
  operatorId?: number;
  keyword?: string;
}): Promise<AdminAuditPage> {
  return get<AdminAuditPage>('/admin/audit-logs', { params });
}

/** 库里出现过的动作名，给筛选下拉用（不硬编码在页面里）。 */
export async function listAuditActions(): Promise<string[]> {
  return get<string[]>('/admin/audit-logs/actions');
}
