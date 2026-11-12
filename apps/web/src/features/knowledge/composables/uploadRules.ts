import { ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES } from '@/constants/app';

/**
 * 上传前的本地校验（F01）。
 *
 * 后端也会校验一遍（"只接受 .md / .txt" / "文件超过 2MB" / "文件没有正文"），
 * 前端先挡一层是为了不给用户「传完了才失败」的体验。
 */

export interface FileCheck {
  file: File;
  ok: boolean;
  reason?: string;
}

export function extensionOf(name: string): string {
  const i = name.lastIndexOf('.');
  return i < 0 ? '' : name.slice(i).toLowerCase();
}

/** 单文件校验：扩展名 + 大小 */
export function checkFile(file: File): FileCheck {
  const ext = extensionOf(file.name);
  if (!(ALLOWED_EXTENSIONS as readonly string[]).includes(ext)) {
    return { file, ok: false, reason: '只接受 .md / .txt 文件' };
  }
  if (file.size === 0) {
    return { file, ok: false, reason: '文件没有正文' };
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return { file, ok: false, reason: '文件超过 2MB' };
  }
  return { file, ok: true };
}

export interface SplitFiles {
  accepted: File[];
  rejected: Array<{ name: string; reason: string }>;
}

/** 批量校验：一次拖一堆文件进来时逐条给原因 */
export function splitFiles(files: File[]): SplitFiles {
  const accepted: File[] = [];
  const rejected: Array<{ name: string; reason: string }> = [];
  for (const file of files) {
    const result = checkFile(file);
    if (result.ok) accepted.push(file);
    else rejected.push({ name: file.name, reason: result.reason ?? '无法上传' });
  }
  return { accepted, rejected };
}

/** 大小显示：KB / MB */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}
