#!/usr/bin/env node
/**
 * 从 docs/api/openapi-public.yaml 生成 src/types/api.generated.ts。
 *
 * 契约唯一源头是 YAML（规格 §7.6），前端类型必须由它生成，禁止手改漂移。
 * 本轮 YAML 尚未产出时脚本优雅退出（退出码 0），不影响门禁；
 * YAML 就绪后直接 `npm run gen:api`，再把 src/types/api.d.ts 的手写模型改为 re-export。
 */
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');
const REPO_ROOT = resolve(ROOT, '..');
const YAML = resolve(REPO_ROOT, 'docs', 'api', 'openapi-public.yaml');
const OUT = resolve(ROOT, 'src', 'types', 'api.generated.ts');

if (!existsSync(YAML)) {
  process.stdout.write(`[gen:api] 未找到契约文件：${YAML}\n`);
  process.stdout.write(
    '[gen:api] 本轮跳过（前端使用 src/types/api.d.ts 手写模型）；YAML 就绪后重跑本脚本即可。\n',
  );
  process.exit(0);
}

mkdirSync(dirname(OUT), { recursive: true });

const isWin = process.platform === 'win32';
execFileSync(isWin ? 'npx.cmd' : 'npx', ['openapi-typescript', YAML, '-o', OUT], {
  cwd: ROOT,
  encoding: 'utf8',
  shell: isWin,
  stdio: 'inherit',
});

const banner = [
  '/* eslint-disable */',
  '/**',
  ' * 本文件由 scripts/gen-api-types.mjs 从 docs/api/openapi-public.yaml 自动生成。',
  ' * 请勿手改：契约变更请改 YAML 后重跑 npm run gen:api。',
  ' */',
  '',
].join('\n');

writeFileSync(OUT, banner + readFileSync(OUT, 'utf8'), 'utf8');
process.stdout.write(`[gen:api] 已生成 ${OUT}\n`);
