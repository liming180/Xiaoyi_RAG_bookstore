#!/usr/bin/env node
/**
 * 契约漂移检查：手写视图类型（src/types/api.d.ts）↔ 生成契约（src/types/api.generated.ts）。
 *
 * 背景：docs/api/openapi-public.yaml 是契约唯一源头，前端类型由 `npm run gen:api` 生成。
 * 业务代码仍用 api.d.ts 里的手写视图模型（把 EntityId 收窄成 string、把可空字段显式标出），
 * 于是存在「生成契约改了、手写视图没跟」的漂移风险。本脚本把这件事变成门禁：
 *
 *   - 属性名缺失 / 多出 → 失败
 *   - 只比属性名，不比类型：nullability 与 string|number 收窄属于有意差异，写在 API_D.ts 注释里
 *
 * 用法：node scripts/check-contract-drift.mjs [--json]
 * 退出码：0 = 无漂移，1 = 有漂移或文件缺失。
 */
import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');
const DTS = resolve(ROOT, 'src', 'types', 'api.d.ts');
const GENERATED = resolve(ROOT, 'src', 'types', 'api.generated.ts');

/** 手写接口 → 生成 schema 的对应关系。没列出的手写类型不参与比对（如 Result/Page 是包装层）。 */
const PAIRS = [
  ['LoginRequest', 'LoginRequest'],
  ['LoginResult', 'LoginResult'],
  ['UserInfo', 'UserInfo'],
  ['AdminUserItem', 'AdminUserItem'],
  ['AdminUserPage', 'AdminUserPage'],
  ['AdminAuditItem', 'AdminAuditItem'],
  ['AdminAuditPage', 'AdminAuditPage'],
  ['Conversation', 'Conversation'],
  ['Citation', 'Citation'],
  ['TraceRow', 'TraceRow'],
  ['RetrievalTrace', 'RetrievalTrace'],
  ['Message', 'Message'],
  ['ChatRequest', 'ChatRequest'],
  ['DocumentMeta', 'DocumentMeta'],
  ['UploadSkipped', 'UploadSkipped'],
  ['UploadResult', 'UploadResult'],
  ['IndexStatus', 'IndexStatus'],
  ['IndexTask', 'IndexTask'],
  ['RebuildRequest', 'RebuildRequest'],
  ['ChunkItem', 'ChunkItem'],
  ['EvalQuestion', 'EvalQuestion'],
  ['EvalCaseResult', 'EvalCaseResult'],
  ['EvalStats', 'EvalStats'],
  ['EvalRunSummary', 'EvalRunSummary'],
  ['EvalBatchRequest', 'EvalBatchRequest'],
  ['FeedbackRequest', 'FeedbackRequest'],
  ['FeedbackSummary', 'FeedbackSummary'],
  ['EvalCandidate', 'EvalCandidate'],
  ['ExperimentAxis', 'ExperimentAxis'],
  ['ExperimentParams', 'ExperimentParams'],
  ['ExperimentMetrics', 'ExperimentMetrics'],
  ['ExperimentRun', 'ExperimentRun'],
  ['Experiment', 'Experiment'],
  ['ExperimentReport', 'ExperimentReport'],
];

/**
 * 有意为之的字段差异：手写视图额外带的字段（生成契约里没有）。
 * 只允许「视图补充」，不允许「生成契约新增字段而视图漏掉」——后者才是漂移。
 */
const VIEW_ONLY_FIELDS = {
  Citation: [],
  TraceRow: [],
  Message: [],
  IndexStatus: [],
  IndexTask: [],
  // 既有差异（非本次改动引入）：题库的启停与来源在契约 schema 里没有落，
  // 但前端视图层需要它们来渲染题型开关与「反馈候选转正」的标记。
  // 登记为「视图补充」而不是悄悄放过：将来契约补齐这两个字段时，
  // 这里要同步删掉，否则会掩盖真正的反向漂移。
  EvalQuestion: ['enabled', 'source'],
  EvalBatchRequest: ['types', 'limit', 'sample'],
};

function readOrFail(path, label) {
  if (!existsSync(path)) {
    throw new Error(`${label} 不存在：${path}`);
  }
  return readFileSync(path, 'utf8');
}

/** 从 api.d.ts 里抽出手写 interface 的顶层属性名。 */
export function handwrittenProps(source) {
  const out = new Map();
  const re = /export interface (\w+)[^{]*\{([\s\S]*?)\n\}/g;
  let m;
  while ((m = re.exec(source)) !== null) {
    const [, name, body] = m;
    const props = [];
    for (const raw of body.split('\n')) {
      const line = raw.trim();
      if (!line || line.startsWith('/**') || line.startsWith('*') || line.startsWith('//')) continue;
      const field = /^([A-Za-z_][\w]*)\??\s*:/.exec(line);
      if (field) props.push(field[1]);
    }
    out.set(name, props);
  }
  return out;
}

/** 从 api.generated.ts 的 components.schemas 里抽出每个 schema 的顶层属性名。 */
export function generatedProps(source) {
  const start = source.indexOf('export interface components');
  if (start < 0) throw new Error('api.generated.ts 里找不到 components');
  const tail = source.slice(start);
  const out = new Map();
  // 顶层 schema 缩进 8 空格，属性缩进 12 空格
  const re = /\n {8}(\w+): \{([\s\S]*?)\n {8}\};/g;
  let m;
  while ((m = re.exec(tail)) !== null) {
    const [, name, body] = m;
    const props = [];
    for (const raw of body.split('\n')) {
      if (!/^ {12}\S/.test(raw)) continue;
      const line = raw.trim();
      if (line.startsWith('/*') || line.startsWith('*') || line.startsWith('//')) continue;
      const field = /^([A-Za-z_][\w]*)\??\s*:/.exec(line);
      if (field) props.push(field[1]);
    }
    out.set(name, props);
  }
  return out;
}

export function checkDrift() {
  const hand = handwrittenProps(readOrFail(DTS, '手写视图类型'));
  const gen = generatedProps(readOrFail(GENERATED, '生成契约类型'));
  const problems = [];
  const checked = [];

  for (const [handName, genName] of PAIRS) {
    const handProps = hand.get(handName);
    const genProps = gen.get(genName);
    if (!handProps) {
      problems.push(`api.d.ts 缺少 interface ${handName}`);
      continue;
    }
    if (!genProps) {
      problems.push(`api.generated.ts 缺少 schema ${genName}（契约里改名或删除了？）`);
      continue;
    }
    const allowed = new Set(VIEW_ONLY_FIELDS[handName] ?? []);
    const handSet = new Set(handProps);
    const genSet = new Set(genProps);

    const missing = genProps.filter((p) => !handSet.has(p));
    if (missing.length) {
      problems.push(`${handName} 漏了契约字段：${missing.join(', ')}`);
    }
    const extra = handProps.filter((p) => !genSet.has(p) && !allowed.has(p));
    if (extra.length) {
      problems.push(`${handName} 多出契约没有的字段：${extra.join(', ')}`);
    }
    checked.push(handName);
  }

  return { ok: problems.length === 0, checked, problems };
}

const isMain = process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url));
if (isMain) {
  let result;
  try {
    result = checkDrift();
  } catch (error) {
    process.stderr.write(`[contract-drift] ${error.message}\n`);
    process.exit(1);
  }
  if (process.argv.includes('--json')) {
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  } else if (result.ok) {
    process.stdout.write(`[contract-drift] ${result.checked.length} 个接口与契约一致\n`);
  } else {
    process.stdout.write('[contract-drift] 发现漂移：\n');
    for (const p of result.problems) process.stdout.write(`  - ${p}\n`);
  }
  process.exit(result.ok ? 0 : 1);
}

export { PAIRS };
