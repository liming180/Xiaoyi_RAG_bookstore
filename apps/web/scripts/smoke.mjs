#!/usr/bin/env node
/**
 * P6 浏览器冒烟：真实 Chrome 渲染 + 截图。
 *
 * 为什么不用 jsdom 测试替代：
 * 1. jsdom 不做真实布局与样式计算，CSS 变量、响应式断点、sticky 定位全都测不出来；
 * 2. 「构建产物能不能跑」只有真浏览器能回答 —— vite build 通过不代表运行时没有
 *    例如顶层 await、循环依赖、service worker 注册路径之类的坑。
 *
 * 关键决策：冒烟用 **production 构建（VITE_USE_MOCK=false）+ 本地 stub API**，
 * 而不是开发构建里的 MSW。
 * 原因：MSW 依赖 service worker 注册，`--headless=new --dump-dom` 下
 * `startMockWorker()` 的 `waitUntilReady()` 等不到 controller，页面永远不 mount
 * （实测 DOM 停在 917B 的空壳）。stub API 由本脚本自己起，同源、同步、
 * 且顺带验证了 axios 那条真实 HTTP 链路，比走 service worker 更接近真联调。
 *
 * 用法：node scripts/smoke.mjs [--keep]
 *   --keep  保留 dist-smoke/ 与临时 profile（排查用）
 */
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { extname, join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('..', import.meta.url)));
const DIST = join(ROOT, 'dist-smoke');
const OUT_DIR = join(ROOT, 'test-artifacts');
const SHOT_DIR = join(OUT_DIR, 'screenshots');
const PROFILE = join(ROOT, '.chrome-smoke-profile');
const PORT = 4178;
const ORIGIN = `http://127.0.0.1:${PORT}`;
const KEEP = process.argv.includes('--keep');

const CHROME_CANDIDATES = [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  `${process.env.LOCALAPPDATA ?? ''}/Google/Chrome/Application/chrome.exe`,
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
];

/** 每条路由要断言的 testid；缺一个就判定这条路由没渲染成功。 */
const ROUTES = [
  {
    path: '/login',
    name: 'login',
    title: '登录页',
    expect: ['page-login', 'login-auth-note', 'login-form'],
    auth: false,
  },
  {
    path: '/chat',
    name: 'chat',
    title: '对话页',
    expect: ['app-shell', 'app-topbar', 'app-sidebar', 'page-chat', 'chat-input'],
    auth: true,
  },
  {
    path: '/knowledge',
    name: 'knowledge',
    title: '知识库页',
    expect: ['app-shell', 'page-knowledge', 'document-table', 'build-panel'],
    auth: true,
  },
  {
    path: '/knowledge/chunks',
    name: 'chunks',
    title: '片段浏览页',
    expect: ['app-shell', 'page-chunks', 'chunk-side', 'chunk-count'],
    auth: true,
  },
  {
    path: '/eval',
    name: 'eval',
    title: '评测页',
    expect: ['app-shell', 'page-eval', 'eval-tabs', 'batch-runner'],
    auth: true,
  },
];

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.map': 'application/json; charset=utf-8',
};

/* ------------------------------------------------------------ stub 数据 */

const DOCS = [
  {
    id: 'D01',
    name: '01_活动说明.md',
    title: '活动说明',
    tags: ['活动'],
    version: 'v1',
    charCount: 420,
    chunkCount: 2,
    status: 'INDEXED',
    verified: true,
    updatedAt: 1_700_000_000_000,
  },
  {
    id: 'D02',
    name: '02_借阅规则.md',
    title: '借阅规则',
    tags: ['借阅'],
    version: 'v1',
    charCount: 380,
    chunkCount: 2,
    status: 'INDEXED',
    verified: true,
    updatedAt: 1_700_000_000_000,
  },
  {
    id: 'D06',
    name: '06_成员留言摘录.md',
    title: '成员留言摘录',
    tags: ['留言'],
    version: 'v1',
    charCount: 300,
    chunkCount: 2,
    status: 'INDEXED',
    verified: false,
    updatedAt: 1_700_000_000_000,
  },
];

const CHUNKS = [
  {
    chunkId: 'D01-C001',
    docId: 'D01',
    docTitle: '活动说明',
    headingPath: '# 星河读书会活动说明',
    text: '星河读书会每月举办一次共读活动，成员可自由参加，场地在社区活动室。',
    start: 0,
    end: 34,
    kind: 'chunk',
    verified: true,
  },
  {
    chunkId: 'D01-C002',
    docId: 'D01',
    docTitle: '活动说明',
    headingPath: '# 星河读书会活动说明',
    text: '共读活动的书目由成员投票决定，每次活动前一周公布。',
    start: 25,
    end: 55,
    kind: 'chunk',
    verified: true,
  },
  {
    chunkId: 'D02-C001',
    docId: 'D02',
    docTitle: '借阅规则',
    headingPath: '# 星河读书会借阅规则',
    text: '每位成员一次最多借阅 4 本，借期 21 天，可续借一次。',
    start: 0,
    end: 28,
    kind: 'chunk',
    verified: true,
  },
  {
    chunkId: 'D02-C002',
    docId: 'D02',
    docTitle: '借阅规则',
    headingPath: '# 星河读书会借阅规则',
    text: '逾期未还将暂停借阅资格，续借需在到期前办理。',
    start: 20,
    end: 46,
    kind: 'chunk',
    verified: true,
  },
];

const QUESTIONS = [
  { id: 'T01', type: 'single', question: '一次最多能借几本书？', keywords: '4/四', evidence: 'D02' },
  { id: 'T02', type: 'single', question: '借期是多少天？', keywords: '21', evidence: 'D02' },
  { id: 'T03', type: 'cross', question: '借阅与续借分别有什么限制？', keywords: '4|21', evidence: 'D02' },
  { id: 'T04', type: 'out', question: '读书会有没有海外分会？', keywords: '未提及', evidence: '' },
];

const CONVERSATIONS = [
  { id: 'c-demo', title: '演示会话', createdAt: 1_700_000_000_000, updatedAt: 1_700_000_000_000, messageCount: 0 },
];

const ok = (data) => JSON.stringify({ code: 0, message: 'ok', data, timestamp: Date.now() });

/**
 * stub 后端：只覆盖各页面挂载时会打的只读接口。
 * 未命中的 /api/v1 路径统一回 `data: null`，保证页面不会因为 404 卡在加载态。
 */
function stubApi(pathname, method) {
  if (method !== 'GET') return ok(null);
  const path = pathname.replace(/^\/api\/v1/, '');

  if (path === '/auth/profile') return ok({ id: 1, username: 'demo', displayName: '演示用户' });
  if (path === '/conversations') return ok(CONVERSATIONS);
  if (/^\/conversations\/[^/]+\/messages$/.test(path)) return ok([]);
  if (path === '/index/status')
    return ok({
      status: 'ready',
      chunkSize: 180,
      overlap: 30,
      chunkCount: CHUNKS.length,
      docCount: DOCS.length,
    });
  if (path === '/documents') return ok(DOCS);
  if (path === '/chunks') return ok(CHUNKS);
  if (path === '/eval/questions') return ok(QUESTIONS);
  if (path === '/eval/runs') return ok([]);
  if (path === '/eval/candidates') return ok([]);
  if (path === '/feedback/summary') return ok({ total: 0, up: 0, down: 0, candidates: 0 });
  return ok(null);
}

/* ------------------------------------------------------------ 进程与服务器 */

function log(message) {
  process.stdout.write(`[smoke] ${message}\n`);
}

function run(cmd, args, options = {}) {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(cmd, args, {
      cwd: ROOT,
      // 默认不开 shell：Chrome 的安装路径含空格，经 cmd.exe 转发会被拆词
      // （实测报 `The syntax of the command is incorrect.`）。
      // npx 在 Windows 上是 .cmd，那种情况由调用方显式传 shell: true。
      shell: false,
      stdio: ['ignore', 'pipe', 'pipe'],
      ...options,
    });
    let stdout = '';
    let stderr = '';
    child.stdout?.on('data', (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr?.on('data', (chunk) => {
      stderr += chunk.toString();
    });
    child.on('error', rejectPromise);
    child.on('close', (code) => resolvePromise({ code: code ?? 0, stdout, stderr }));
  });
}

function findChrome() {
  for (const candidate of CHROME_CANDIDATES) {
    if (candidate && existsSync(candidate)) return candidate;
  }
  return null;
}

/**
 * 零依赖静态服务器 + stub API。
 *
 * `/__seed.html` 是运行时生成的：它只在冒烟期间存在，用来给同源页面写
 * localStorage 里的 token（路由守卫要求登录态）。不往 public/ 放这个文件，
 * 是为了避免它被打进正式产物。
 */
function startServer() {
  const seedHtml = (target, theme = 'light') => `<!doctype html><meta charset="utf-8"><script>
localStorage.setItem('xiaoyi.token', 'smoke-token');
localStorage.setItem('xiaoyi.mode', 'rag');
localStorage.setItem('xiaoyi.k', '3');
localStorage.setItem('xiaoyi.theme', ${JSON.stringify(theme)});
location.replace(${JSON.stringify(target)});
</script>`;

  const server = createServer((req, res) => {
    const url = new URL(req.url ?? '/', ORIGIN);
    const pathname = decodeURIComponent(url.pathname);

    if (pathname === '/__seed.html') {
      const target = url.searchParams.get('to') ?? '/chat';
      const theme = url.searchParams.get('theme') === 'dark' ? 'dark' : 'light';
      res.writeHead(200, { 'Content-Type': MIME['.html'], 'Cache-Control': 'no-store' });
      res.end(seedHtml(target, theme));
      return;
    }

    if (pathname.startsWith('/api/v1')) {
      res.writeHead(200, { 'Content-Type': MIME['.json'], 'Cache-Control': 'no-store' });
      res.end(stubApi(pathname, req.method ?? 'GET'));
      return;
    }

    let filePath = join(DIST, normalize(pathname).replace(/^([/\\])+/, ''));
    if (existsSync(filePath) && statSync(filePath).isDirectory()) {
      filePath = join(filePath, 'index.html');
    }
    if (!existsSync(filePath)) {
      // SPA fallback：/chat/:id、/knowledge/chunks 这类前端路由都要回 index.html
      filePath = join(DIST, 'index.html');
    }
    if (!existsSync(filePath)) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('dist-smoke 缺失，先跑 build');
      return;
    }
    res.writeHead(200, { 'Content-Type': MIME[extname(filePath)] ?? 'application/octet-stream' });
    res.end(readFileSync(filePath));
  });

  return new Promise((resolvePromise, rejectPromise) => {
    server.once('error', rejectPromise);
    server.listen(PORT, '127.0.0.1', () => resolvePromise(server));
  });
}

/* ------------------------------------------------------------ Chrome */

function chromeArgs(url, windowSize = '1600,950') {
  return [
    '--headless=new',
    '--disable-gpu',
    '--hide-scrollbars',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    '--disable-dev-shm-usage',
    // 等懒加载 chunk、stub 请求、动画都稳定下来再截图
    '--virtual-time-budget=15000',
    `--window-size=${windowSize}`,
    `--user-data-dir=${PROFILE}`,
    url,
  ];
}

async function dumpDom(chrome, url, windowSize) {
  const { stdout } = await run(chrome, [...chromeArgs(url, windowSize), '--dump-dom']);
  return stdout;
}

async function screenshot(chrome, url, file, windowSize) {
  await run(chrome, [...chromeArgs(url, windowSize), `--screenshot=${file}`]);
  return existsSync(file) ? statSync(file).size : 0;
}

/* ------------------------------------------------------------ 主流程 */

async function main() {
  const startedAt = Date.now();
  mkdirSync(SHOT_DIR, { recursive: true });

  const chrome = findChrome();
  if (!chrome) {
    log('未找到 Chrome/Edge，冒烟跳过');
    writeFileSync(
      join(OUT_DIR, 'smoke.json'),
      `${JSON.stringify({ pass: false, reason: 'no-browser', at: Date.now() }, null, 2)}\n`,
      'utf8',
    );
    process.exitCode = 1;
    return;
  }
  log(`浏览器：${chrome}`);

  log('构建产物（vite build → dist-smoke/）…');
  const build = await run(
    'npx',
    ['vite', 'build', '--outDir', 'dist-smoke', '--emptyOutDir'],
    { shell: true },
  );
  if (build.code !== 0) {
    process.stderr.write(build.stderr || build.stdout);
    throw new Error('冒烟构建失败');
  }
  log('构建完成');

  rmSync(PROFILE, { recursive: true, force: true });
  const server = await startServer();
  log(`静态服务器 + stub API 就绪：${ORIGIN}`);

  const results = [];
  try {
    for (const route of ROUTES) {
      const target = `${ORIGIN}${route.path}`;
      if (route.auth) {
        // 先在同一 profile 里跑一次 seed，把 token 写进 localStorage，
        // 后续导航才不会被路由守卫踢回 /login
        await dumpDom(chrome, `${ORIGIN}/__seed.html?to=${encodeURIComponent(route.path)}`);
      }

      const dom = await dumpDom(chrome, target);
      const missing = route.expect.filter((id) => !dom.includes(`data-testid="${id}"`));
      const shot = join(SHOT_DIR, `${route.name}.png`);
      const bytes = await screenshot(chrome, target, shot);

      const ok = missing.length === 0 && bytes > 0;
      results.push({
        route: route.path,
        title: route.title,
        ok,
        missing,
        screenshot: `test-artifacts/screenshots/${route.name}.png`,
        screenshotBytes: bytes,
        domBytes: dom.length,
      });
      log(
        `${ok ? 'PASS' : 'FAIL'} ${route.path}  DOM ${dom.length}B  截图 ${bytes}B` +
          (missing.length ? `  缺 ${missing.join(',')}` : ''),
      );
    }

    /* ---------------------------------------------------- 深色主题 + 窄屏 */
    // 主题与响应式都是 CSS 变量驱动的，jsdom 测不出来，只能在真浏览器里落一张图。
    // 判定标准：<html data-theme> 真的翻转 + 截图里 --bg 真的换了颜色（靠人工看图 + 字节数）。
    await dumpDom(chrome, `${ORIGIN}/__seed.html?to=${encodeURIComponent('/chat')}&theme=dark`);
    const darkDom = await dumpDom(chrome, `${ORIGIN}/chat`);
    const darkShot = join(SHOT_DIR, 'chat-dark.png');
    const darkBytes = await screenshot(chrome, `${ORIGIN}/chat`, darkShot);
    const darkOk = darkDom.includes('data-theme="dark"') && darkBytes > 0;
    results.push({
      route: '/chat (深色)',
      title: '对话页深色主题',
      ok: darkOk,
      missing: darkDom.includes('data-theme="dark"') ? [] : ['data-theme="dark"'],
      screenshot: 'test-artifacts/screenshots/chat-dark.png',
      screenshotBytes: darkBytes,
      domBytes: darkDom.length,
    });
    log(`${darkOk ? 'PASS' : 'FAIL'} 深色主题  DOM ${darkDom.length}B  截图 ${darkBytes}B`);

    // 窄屏（900×720）走抽屉导航：AppSidebar 从侧栏挪进 el-drawer，
    // 顶栏出现 nav-toggle 悬浮按钮。窗口尺寸只能靠 Chrome 参数控制。
    await dumpDom(chrome, `${ORIGIN}/__seed.html?to=${encodeURIComponent('/chat')}`);
    const narrowShot = join(SHOT_DIR, 'chat-narrow.png');
    const narrowBytes = await screenshot(chrome, `${ORIGIN}/chat`, narrowShot, '900,720');
    const narrowOk = narrowBytes > 0;
    results.push({
      route: '/chat (窄屏 900×720)',
      title: '对话页窄屏',
      ok: narrowOk,
      missing: [],
      screenshot: 'test-artifacts/screenshots/chat-narrow.png',
      screenshotBytes: narrowBytes,
      domBytes: 0,
    });
    log(`${narrowOk ? 'PASS' : 'FAIL'} 窄屏 900×720  截图 ${narrowBytes}B`);
  } finally {
    server.close();
  }

  const pass = results.every((item) => item.ok);
  const report = {
    pass,
    at: Date.now(),
    origin: ORIGIN,
    browser: chrome,
    elapsedMs: Date.now() - startedAt,
    routes: results,
  };
  writeFileSync(join(OUT_DIR, 'smoke.json'), `${JSON.stringify(report, null, 2)}\n`, 'utf8');

  if (!KEEP) {
    rmSync(DIST, { recursive: true, force: true });
    rmSync(PROFILE, { recursive: true, force: true });
  }

  log(pass ? '🎉 冒烟全部通过' : '❌ 冒烟存在失败路由');
  if (!pass) process.exitCode = 1;
}

main().catch((error) => {
  process.stderr.write(`[smoke] 失败：${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
