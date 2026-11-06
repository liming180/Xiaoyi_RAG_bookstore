#!/usr/bin/env node
/**
 * 阶段门禁脚本。
 *
 * 用法：node scripts/gate.mjs P1        # lint / typecheck / test
 *      node scripts/gate.mjs P6 --build # 追加 vite build（P6 最终门禁）
 *
 * 依次执行 lint / typecheck / test 三道门禁，任一失败即整体失败，
 * 结果写入 test-artifacts/gate-<阶段>.json，供「必须过门禁才能进下一阶段」的流程审计。
 *
 * 退出码：0 = 全绿，1 = 有门禁未通过。
 */
import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');
const PHASE = process.argv[2] ?? 'unknown';
const isWin = process.platform === 'win32';

const GATES = [
  { key: 'lint', label: 'ESLint', cmd: 'npx', args: ['eslint', '.', '--max-warnings', '0'] },
  { key: 'typecheck', label: 'vue-tsc', cmd: 'npx', args: ['vue-tsc', '--noEmit'] },
  { key: 'test', label: 'vitest', cmd: 'npx', args: ['vitest', 'run', '--reporter', 'dot'] },
  {
    key: 'contract',
    label: 'contract drift',
    cmd: 'node',
    args: ['scripts/check-contract-drift.mjs'],
  },
];

/** 传 --build 时追加生产构建门禁（构建产物 + 体积报告） */
if (process.argv.includes('--build')) {
  GATES.push({ key: 'build', label: 'vite build', cmd: 'npx', args: ['vite', 'build'] });
}

function run(cmd, args) {
  const started = Date.now();
  // node 用当前解释器（Windows 上没有 node.cmd）；npx 等仍走 .cmd 包装
  const isNode = cmd === 'node';
  const file = isNode ? process.execPath : isWin ? `${cmd}.cmd` : cmd;
  const res = spawnSync(file, args, {
    cwd: ROOT,
    encoding: 'utf8',
    shell: isWin && !isNode,
    maxBuffer: 32 * 1024 * 1024,
  });
  const elapsedMs = Date.now() - started;
  const stdout = res.stdout ?? '';
  const stderr = res.stderr ?? '';
  return {
    ok: res.status === 0,
    exitCode: res.status ?? 1,
    elapsedMs,
    stdout,
    stderr,
  };
}

/** 从 vitest dot reporter 输出里抠出用例数（拿不到就返回 null，不阻塞门禁） */
function parseTestCounts(text) {
  const files = /Test Files\s+(?:(\d+)\s+passed)?(?:\s*\|\s*(\d+)\s+failed)?/.exec(text);
  const tests = /Tests\s+(?:(\d+)\s+passed)?(?:\s*\|\s*(\d+)\s+failed)?/.exec(text);
  return {
    filesPassed: files?.[1] ? Number(files[1]) : 0,
    filesFailed: files?.[2] ? Number(files[2]) : 0,
    testsPassed: tests?.[1] ? Number(tests[1]) : 0,
    testsFailed: tests?.[2] ? Number(tests[2]) : 0,
  };
}

/** 从 vite build 输出里抠出产物体积表（key=build 时用） */
function parseBuildSizes(text) {
  const rows = [];
  const re = /^dist\/(\S+)\s+([\d.,]+)\s+kB\s+│\s+gzip:\s+([\d.,]+)\s+kB/mg;
  let m;
  while ((m = re.exec(text)) !== null) {
    rows.push({
      file: `dist/${m[1]}`,
      rawKb: Number(m[2].replace(/,/g, '')),
      gzipKb: Number(m[3].replace(/,/g, '')),
    });
  }
  return rows;
}

const results = [];
let allOk = true;

for (const gate of GATES) {
  process.stdout.write(`\n=== 门禁 ${PHASE} · ${gate.label} ===\n`);
  const res = run(gate.cmd, gate.args);
  const tail = (res.stdout + res.stderr).trim().split('\n').slice(-25).join('\n');
  process.stdout.write(`${tail}\n`);
  process.stdout.write(`${res.ok ? '✅ 通过' : '❌ 未通过'} (${res.elapsedMs}ms)\n`);

  if (!res.ok) allOk = false;
  results.push({
    key: gate.key,
    label: gate.label,
    ok: res.ok,
    exitCode: res.exitCode,
    elapsedMs: res.elapsedMs,
    command: `${gate.cmd} ${gate.args.join(' ')}`,
    tail,
    ...(gate.key === 'test' ? { counts: parseTestCounts(res.stdout + res.stderr) } : {}),
    ...(gate.key === 'build' ? { sizes: parseBuildSizes(res.stdout + res.stderr) } : {}),
  });
}

const report = {
  phase: PHASE,
  pass: allOk,
  timestamp: new Date().toISOString(),
  node: process.version,
  gates: results,
};

const outDir = resolve(ROOT, 'test-artifacts');
mkdirSync(outDir, { recursive: true });
const outFile = resolve(outDir, `gate-${PHASE}.json`);
writeFileSync(outFile, `${JSON.stringify(report, null, 2)}\n`, 'utf8');

process.stdout.write(`\n报告已写入 ${outFile}\n`);
process.stdout.write(allOk ? `\n🎉 门禁 ${PHASE} 全部通过\n` : `\n🚫 门禁 ${PHASE} 未通过\n`);
process.exit(allOk ? 0 : 1);
