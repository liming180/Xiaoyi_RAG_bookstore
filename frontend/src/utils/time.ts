/**
 * 时间工具：Unix 秒 / 毫秒归一化（A-1 修复，2026-11-09）。
 *
 * 问题：Java 后端返回的是 **Unix 秒**（如 1794205832），前端多处直接
 * `new Date(ts)` 按毫秒解析，结果显示成 1970-01-22 —— 历史评测、候选池、
 * 消息气泡三处都中招，8 条评测记录的时间全部变成无效值。
 *
 * 为什么不改后端：秒级时间戳是常见契约（Java `Instant.getEpochSecond()`、
 * Python `time.time()`），改后端会影响已部署的调用方；归一化是纯前端职责。
 *
 * 判定阈值取 1e11：毫秒级时间戳在 2001 年就超过这个数量级，
 * 而秒级要到公元 5138 年才达到，两者不会混淆。
 */

/** Unix 秒 / 毫秒 → 毫秒。null / 0 返回 0。 */
export function toMillis(ts: number | null | undefined): number {
  if (!ts) return 0;
  return ts < 1e11 ? ts * 1000 : ts;
}

/** 时间戳 → `2026-11-09 14:30` */
export function formatDateTime(ts: number | null | undefined): string {
  const ms = toMillis(ts);
  if (!ms) return '—';
  const d = new Date(ms);
  const p = (n: number): string => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** 时间戳 → `14:30`（气泡用） */
export function formatClock(ts: number | null | undefined): string {
  const ms = toMillis(ts);
  if (!ms) return '';
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** 时间戳 → `3 小时前` */
export function formatAgo(ts: number | null | undefined): string {
  const ms = toMillis(ts);
  if (!ms) return '';
  const m = Math.round((Date.now() - ms) / 60000);
  if (m < 1) return '刚刚';
  if (m < 60) return `${m} 分钟前`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.round(h / 24)} 天前`;
}

/** 两个时间戳之间的耗时 → `34s` / `2m 59s`；缺任一值返回 `—` */
export function formatDuration(
  from: number | null | undefined,
  to: number | null | undefined,
): string {
  if (!from || !to) return '—';
  const s = Math.round((toMillis(to) - toMillis(from)) / 1000);
  if (s < 0) return '—';
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}
