#!/usr/bin/env node
/**
 * 阶段快照：保存 / 还原 src 与配置文件，用于阶段回滚。
 *
 * 用法：
 *   node scripts/snapshot.mjs save P1      # 保存当前状态为 P1
 *   node scripts/snapshot.mjs restore P1   # 还原到 P1
 *   node scripts/snapshot.mjs list         # 列出已保存的快照
 */
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');
const SNAP_ROOT = resolve(ROOT, '.snapshots');

/** 需要纳入快照的路径（相对 frontend/） */
const TARGETS = [
  'src',
  'test',
  'scripts',
  'public',
  'index.html',
  'package.json',
  'vite.config.ts',
  'tsconfig.json',
  'tsconfig.app.json',
  'tsconfig.node.json',
  'eslint.config.js',
  '.prettierrc.json',
  '.env.development',
  '.env.production',
  '.env.example',
];

const [, , action, name] = process.argv;

function list() {
  if (!existsSync(SNAP_ROOT)) {
    process.stdout.write('（还没有任何快照）\n');
    return;
  }
  for (const entry of readdirSync(SNAP_ROOT)) {
    const full = resolve(SNAP_ROOT, entry);
    if (statSync(full).isDirectory()) process.stdout.write(`- ${entry}\n`);
  }
}

function save(snapshotName) {
  const dest = resolve(SNAP_ROOT, snapshotName);
  rmSync(dest, { recursive: true, force: true });
  mkdirSync(dest, { recursive: true });
  let count = 0;
  for (const target of TARGETS) {
    const from = resolve(ROOT, target);
    if (!existsSync(from)) continue;
    cpSync(from, resolve(dest, target), { recursive: true });
    count += 1;
  }
  process.stdout.write(`已保存快照 ${snapshotName}（${count} 项）→ ${dest}\n`);
}

function restore(snapshotName) {
  const src = resolve(SNAP_ROOT, snapshotName);
  if (!existsSync(src)) {
    process.stderr.write(`快照不存在：${src}\n`);
    process.exit(1);
  }
  let count = 0;
  for (const target of TARGETS) {
    const from = resolve(src, target);
    if (!existsSync(from)) continue;
    const to = resolve(ROOT, target);
    rmSync(to, { recursive: true, force: true });
    cpSync(from, to, { recursive: true });
    count += 1;
  }
  process.stdout.write(`已还原快照 ${snapshotName}（${count} 项）\n`);
}

switch (action) {
  case 'save':
    if (!name) {
      process.stderr.write('用法：node scripts/snapshot.mjs save <名称>\n');
      process.exit(1);
    }
    save(name);
    break;
  case 'restore':
    if (!name) {
      process.stderr.write('用法：node scripts/snapshot.mjs restore <名称>\n');
      process.exit(1);
    }
    restore(name);
    break;
  case 'list':
    list();
    break;
  default:
    process.stdout.write('用法：node scripts/snapshot.mjs <save|restore|list> [名称]\n');
    process.exit(1);
}
