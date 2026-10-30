/**
 * CSV 序列化与下载。
 *
 * 两个关键点，都是踩过的坑：
 *  1. **必须带 UTF-8 BOM**（`\uFEFF`）。Excel 在 Windows 上默认按 GBK 打开 CSV，
 *     没有 BOM 时中文会变成乱码。F09 验收里「导出 CSV 可用 Excel 打开」就是这一条。
 *  2. 转义规则按 RFC 4180：字段含逗号、双引号、换行时必须整体加双引号，
 *     内部的双引号要写两遍。漏了任何一条，含逗号的回答就会把列数冲乱。
 */

const BOM = '\uFEFF';

export type CsvCell = string | number | boolean | null | undefined;

/** 转义单个字段（不含包裹，仅处理内部双引号） */
function escapeCell(value: CsvCell): string {
  if (value === null || value === undefined) return '';
  const text = String(value);
  if (/[",\r\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

/**
 * 二维数组 → CSV 文本（含 BOM）。
 *
 * 行分隔用 `\r\n`：Excel 对 `\n` 也能读，但 `\r\n` 是 RFC 4180 的规定，
 * 且 Windows 记事本打开时不会挤成一行。
 */
export function toCsv(rows: CsvCell[][]): string {
  const body = rows.map((row) => row.map(escapeCell).join(',')).join('\r\n');
  return `${BOM}${body}`;
}

/** 把文本包成带 BOM 的 Blob，供下载使用 */
export function csvBlob(content: string): Blob {
  return new Blob([content], { type: 'text/csv;charset=utf-8' });
}

/**
 * 触发浏览器下载。
 *
 * 放在独立函数里，测试可以 spy 它而不真的下载；
 * URL.revokeObjectURL 必须调用，否则 Blob 会一直被引用着不释放。
 */
export function downloadCsv(filename: string, content: string): void {
  const url = URL.createObjectURL(csvBlob(content));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/** 文件名里的时间戳：20261030-2315，避免同名覆盖 */
export function csvTimestamp(date = new Date()): string {
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}`;
}
