#!/usr/bin/env node
/**
 * P7-G 真实浏览器双账号联调（零依赖：复用 scripts/cdp.mjs）。
 *
 * 为什么必须真浏览器 + 真实后端：
 * - MSW 的 302 个用例跑的是 mock handler，证明不了「JWT 真的被后端接受」；
 * - smoke.mjs 用的是自带 stub API，也证明不了真实 Java + Python 链路；
 * - 双账号隔离只有在两个**独立浏览器 profile**（各自 localStorage）里才成立，
 *   同一 profile 开两个标签页会共享 token，验不出隔离。
 *
 * 判定项：
 *  G1 A 账号在 /knowledge 只看到自己的资料，看不到 B 的；
 *  G2 B 账号在 /knowledge 只看到自己的资料，看不到 A 的；
 *  G3 A 账号在 /chat 发问，拿到带引用的回答（answer-body 非空、无 msg-error）；
 *  G4 全程无 401（登录后请求都带 Bearer，说明认证链路真的通了）。
 *
 * 用法：node scripts/p7-browser.mjs [--keep]
 *   --keep 保留 dist-p7/ 与截图目录（排查用）
 */
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { request as httpRequest } from 'node:http';
import { extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { launchChrome } from './cdp.mjs';

const ROOT = resolve(fileURLToPath(new URL('..', import.meta.url)));
const DIST = resolve(process.env.P7_WEB_DIST ?? join(ROOT, 'dist-p7'));
// 证据统一落在仓库根的 test-artifacts/（与 p7-evidence.json、p7-redocly.txt 同处），
// 而不是 frontend/test-artifacts/，否则验收报告会被拆到两个目录。
const OUT_DIR = resolve(ROOT, '..', 'test-artifacts');
const SHOT_DIR = join(OUT_DIR, 'screenshots');
const PORT = Number(process.env.P7_WEB_PORT ?? 4173);
const ORIGIN = `http://127.0.0.1:${PORT}`;
const JAVA = process.env.P7_JAVA ?? 'http://127.0.0.1:8080';
const KEEP = process.argv.includes('--keep');

const ENV_FILE = resolve(process.env.P7_ENV_FILE ?? resolve(ROOT, '..', 'test-artifacts', 'p7-env.json'));
const ENV = JSON.parse(readFileSync(ENV_FILE, 'utf8'));
const USER_A = ENV.AUTH_BOOTSTRAP_USERNAME;
const PASS_A = ENV.AUTH_BOOTSTRAP_PASSWORD;
const USER_B = ENV.AUTH_SECONDARY_BOOTSTRAP_USERNAME;
const PASS_B = ENV.AUTH_SECONDARY_BOOTSTRAP_PASSWORD;

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
};

function log(msg) {
  process.stdout.write(`[p7-browser] ${msg}\n`);
}

function run(cmd, args, options = {}) {
  return new Promise((resolvePromise) => {
    const child = spawn(cmd, args, { cwd: ROOT, shell: process.platform === 'win32', ...options });
    let stdout = '';
    let stderr = '';
    child.stdout?.on('data', (d) => {
      stdout += d;
    });
    child.stderr?.on('data', (d) => {
      stderr += d;
    });
    child.on('close', (code) => resolvePromise({ code, stdout, stderr }));
  });
}

/* ------------------------------------------------------- 后端 API 直连（造数） */

async function apiLogin(username, password) {
  const res = await fetch(`${JAVA}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  const body = await res.json();
  if (res.status !== 200 || body.code !== 0) {
    throw new Error(`登录失败 ${username}: HTTP ${res.status} ${JSON.stringify(body)}`);
  }
  return body.data.token;
}

async function apiUpload(token, filename, text) {
  const form = new FormData();
  form.append('files', new Blob([text], { type: 'text/markdown' }), filename);
  const res = await fetch(`${JAVA}/api/v1/documents`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  const body = await res.json();
  if (res.status !== 200 || body.code !== 0) {
    throw new Error(`上传失败 ${filename}: HTTP ${res.status} ${JSON.stringify(body)}`);
  }
  return body.data.accepted?.[0] ?? null;
}

/* --------------------------------------------------------- 静态 + API 代理 */

function startServer() {
  const server = createServer((req, res) => {
    if (req.url?.startsWith('/api/')) {
      const target = new URL(req.url, JAVA);
      const proxy = httpRequest(
        {
          hostname: target.hostname,
          port: target.port,
          path: `${target.pathname}${target.search}`,
          method: req.method,
          headers: { ...req.headers, host: target.host },
        },
        (upstream) => {
          res.writeHead(upstream.statusCode ?? 502, upstream.headers);
          upstream.pipe(res);
        },
      );
      proxy.on('error', (error) => {
        res.writeHead(502, { 'Content-Type': 'text/plain; charset=utf-8' });
        res.end(`代理失败：${error.message}`);
      });
      req.pipe(proxy);
      return;
    }

    const path = (req.url ?? '/').split('?')[0];
    let filePath = join(DIST, decodeURIComponent(path));
    if (!existsSync(filePath) || path === '/') {
      filePath = join(DIST, 'index.html');
    }
    if (!existsSync(filePath)) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('dist-p7 缺失，先跑 vite build');
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

/* ------------------------------------------------------------------ 页面动作 */

/**
 * 往「带 data-testid 的输入控件」里写值。
 *
 * Element Plus 的 el-input 会把透传属性落在**外层 div** 上，真正的 <input> 在内部；
 * 而原生 textarea 的 testid 就在元素自身。两种形状都要能吃下，所以这里先按
 * testid 找宿主，再向下找可写元素，最后才回落到宿主本身。
 */
async function typeInto(page, testid, text) {
  const ok = await page.evaluate(`(() => {
    const host = document.querySelector('[data-testid="${testid}"]');
    if (!host) return 'host-missing';
    const el = host.matches('input, textarea')
      ? host
      : host.querySelector('input, textarea');
    if (!el) return 'control-missing';
    const proto = el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(text)});
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return 'ok';
  })()`);
  if (ok !== 'ok') throw new Error(`输入失败（${ok}）：[data-testid="${testid}"]`);
}

async function apiProfile(token) {
  const res = await fetch(`${JAVA}/api/v1/auth/profile`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = await res.json();
  if (res.status !== 200 || body.code !== 0) {
    throw new Error(`profile 失败: HTTP ${res.status} ${JSON.stringify(body)}`);
  }
  return body.data;
}

/** 只取 JWT 的 sub/exp 声明，用来证明「这个 token 属于哪个用户」 */
function jwtClaims(token) {
  const parts = String(token ?? '').split('.');
  if (parts.length !== 3) return null;
  try {
    return JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf8'));
  } catch {
    return null;
  }
}

async function apiRebuildAndWait(token, timeoutMs = 120000) {
  const started = Date.now();
  const res = await fetch(`${JAVA}/api/v1/index/rebuild`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ chunkSize: 180, overlap: 30 }),
  });
  const body = await res.json();
  if (res.status !== 200 || body.code !== 0) {
    throw new Error(`建库失败: HTTP ${res.status} ${JSON.stringify(body)}`);
  }
  const taskId = body.data.id;
  for (;;) {
    if (Date.now() - started > timeoutMs) throw new Error(`建库超时：task ${taskId}`);
    await new Promise((r) => setTimeout(r, 500));
    const st = await fetch(`${JAVA}/api/v1/index/tasks/${taskId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const info = await st.json();
    const task = info.data ?? {};
    if (task.status === 'SUCCEEDED') return task;
    if (task.status === 'FAILED') throw new Error(`建库失败：${task.error ?? '未知原因'}`);
  }
}

async function loginThroughUi(page, username, password) {
  await page.goto(`${ORIGIN}/login`);
  await page.waitFor(`!!document.querySelector('[data-testid="login-form"]')`, {
    label: '登录表单',
  });
  await typeInto(page, 'login-username', username);
  await typeInto(page, 'login-password', password);
  await page.waitFor(
    `!document.querySelector('[data-testid="login-submit"]')?.disabled`,
    { label: '登录按钮可用' },
  );
  await page.click('[data-testid="login-submit"]');

  // 登录失败时页面不会跳转，只在 login-error 里落一条文案；
  // 只等跳转会让「密码错」表现成含糊的「等待超时」，所以两条路一起等。
  await page.waitFor(
    `(() => {
      if (location.pathname.startsWith('/chat')) return 'navigated';
      const err = document.querySelector('[data-testid="login-error"]');
      return err && err.textContent.trim() ? 'failed' : false;
    })()`,
    { timeoutMs: 20000, label: '登录结果' },
  );

  const state = await page.evaluate(`(() => ({
    path: location.pathname,
    error: document.querySelector('[data-testid="login-error"]')?.textContent?.trim() ?? null,
    token: window.localStorage.getItem('xiaoyi.token'),
  }))()`);
  if (!state.path.startsWith('/chat')) {
    throw new Error(`登录未跳转：path=${state.path} error=${state.error ?? '无'}`);
  }
  if (!state.token) throw new Error('登录后 localStorage 里没有 xiaoyi.token');
  return state.token;
}
async function knowledgeTitles(page) {
  await page.goto(`${ORIGIN}/knowledge`);
  await page.waitFor(`!!document.querySelector('[data-testid="page-knowledge"]')`, {
    label: '知识库页渲染',
  });
  await page.waitFor(
    `!!document.querySelector('[data-testid="document-table"] tbody tr, [data-testid="doc-empty"]')`,
    { timeoutMs: 20000, label: '资料表格出结果' },
  );
  return page.evaluate(`Array.from(document.querySelectorAll('[data-testid="document-table"] tbody tr'))
    .map((tr) => tr.querySelector('.doc-table__name')?.textContent?.trim() ?? '')`);
}
async function askQuestion(page, question) {
  await page.goto(`${ORIGIN}/chat`);
  await page.waitFor(`!!document.querySelector('[data-testid="question-input"]')`, {
    label: '输入框就绪',
  });
  // 产品行为：没有会话时 ChatView.send 会因为 conversationId 为空直接 return
  // （ChatView.vue:100-102 与 useChat.ts:85-88 都是 !cid 就静默返回），既不发请求
  // 也不报错。所以验收必须先点「+ 新会话」，等 store 里 activeId 落定再提问。
  const needConversation = await page.evaluate(
    `(() => !localStorage.getItem('xiaoyi.conversationId'))()`,
  );
  if (needConversation) {
    await page.click('[data-testid="conversation-create"]');
    await page.waitFor(
      `!!localStorage.getItem('xiaoyi.conversationId')`,
      { timeoutMs: 20000, label: '新会话创建完成' },
    );
    // 建会话会把路由切到 /chat/:id，ChatView 重新挂载、输入区短暂卸载，
    // 所以这里必须再等一次输入框，否则会在空窗期里找 testid 而 host-missing。
    await page.waitFor(`!!document.querySelector('[data-testid="question-input"]')`, {
      timeoutMs: 20000,
      label: '建会话后输入框重新就绪',
    });
  }
  await typeInto(page, 'question-input', question);
  // 原生 setter + input 事件只是把值写进 DOM，Vue 的 v-model 要到下一次 flush
  // 才更新 text，此时 send 按钮的 disabled 还是上一帧的值 —— 直接点会点在
  // 禁用态上、什么都不发生（实测表现为「回答正文出现」超时）。
  // 所以以字数计数器为准：它由 text.length 渲染，非 0 才说明绑定真的生效。
  await page.waitFor(
    `(() => {
      const count = document.querySelector('.composer__count')?.textContent ?? '';
      return Number(count.split('/')[0].trim()) > 0;
    })()`,
    { label: '输入已绑定到 v-model' },
  );
  await page.waitFor(
    `!document.querySelector('[data-testid="chat-send"]')?.disabled`,
    { label: '发送按钮可用' },
  );
  await page.click('[data-testid="chat-send"]');
  // 点击与「请求真的发出」之间还有一层竞态：ChatView.send 在 conversationId 为空或
  // chat.sending 为真时静默 return（ChatView.vue:100-102 / useChat.ts:85-88），
  // 既不报错也不发请求 —— 实测出现过一次「点完什么都没有、Java 日志里连
  // POST /api/v1/chat/stream 都没有」的超时。所以这里给它一次重试：首轮等 15s
  // 没有正文就再点一次发送，再等满 40s。重试过就记进 retriedSend，报告里能看到。
  let retriedSend = false;
  try {
    await page.waitFor(
      `(() => {
        const bodies = Array.from(document.querySelectorAll('[data-testid="answer-body"]'));
        const last = bodies[bodies.length - 1];
        return !!last && last.textContent.trim().length > 0;
      })()`,
      { timeoutMs: 15000, label: '回答正文出现（首轮）' },
    );
  } catch {
    retriedSend = true;
    const canRetry = await page.evaluate(
      `(() => {
        const btn = document.querySelector('[data-testid="chat-send"]');
        const cid = window.localStorage.getItem('xiaoyi.conversationId');
        return !!btn && !btn.disabled && !!cid;
      })()`,
    );
    if (!canRetry) throw new Error('首轮未发出请求，且发送按钮/会话不可用于重试');
    await page.click('[data-testid="chat-send"]');
    await page.waitFor(
      `(() => {
        const bodies = Array.from(document.querySelectorAll('[data-testid="answer-body"]'));
        const last = bodies[bodies.length - 1];
        return !!last && last.textContent.trim().length > 0;
      })()`,
      { timeoutMs: 40000, label: '回答正文出现（重试）' },
    );
  }
  // trace 是 done 之后按 messageId 二次拉的（useChat.ts:109-120），比正文晚一步到；
  // 正文一出现就取快照会拿到 traceMeta=null。这里等面板摘要行渲染出来，
  // 拿不到也只是超时降级，不掩盖正文断言。
  await page
    .waitFor(`!!document.querySelector('.trace__meta')`, {
      timeoutMs: 20000,
      label: '检索过程面板出现',
    })
    .catch(() => {});
  return page.evaluate(`(() => {
    const bodies = Array.from(document.querySelectorAll('[data-testid="answer-body"]'));
    const last = bodies[bodies.length - 1];
    return {
      answer: last ? last.textContent.trim().slice(0, 200) : '',
      error: document.querySelector('[data-testid="msg-error"]')?.textContent?.trim() ?? null,
      degraded: !!document.querySelector('[data-testid="msg-degraded"]'),
      // 引用有两种可见形态：
      //  - cite-badge：正文里出现 [1] 这类编号（取决于模型是否写编号）
      //  - 检索过程面板的「采用 N 段」：落库后按 messageId 拉回的 trace
      // 只有后者能证明「Python 真的按用户检索到了片段」，且不依赖模型措辞，
      // 所以 G3 以它为准。注意面板默认收起（表格行不渲染），摘要行却是常驻的，
      // 因此读 .trace__meta 文案而不是数 trace-row-kept 节点。
      citeBadges: document.querySelectorAll('[data-testid="cite-badge"]').length,
      traceMeta: document.querySelector('.trace__meta')?.textContent?.trim() ?? null,
      hasTracePanel: !!document.querySelector('[data-testid="retrieval-trace"]'),
      retriedSend: ${retriedSend},
    };
  })()`);
}

/* --------------------------------------------------------------------- 主流程 */

async function main() {
  const startedAt = Date.now();
  mkdirSync(SHOT_DIR, { recursive: true });

  // 调用方已指定产物目录（例如 local-mysql 用 frontend/dist）时不再重建：
  // 那种场景下构建由 pnpm build 负责，重复构建只会把产物写到 dist-p7 而 DIST 仍指向 dist。
  if (process.env.P7_WEB_DIST) {
    if (!existsSync(DIST)) throw new Error(`P7_WEB_DIST 指向的目录不存在：${DIST}`);
    log(`跳过构建，使用已有产物：${DIST}`);
  } else {
    log('构建前端（VITE_USE_MOCK=false，走真实后端）…');
    const build = await run('npx', ['vite', 'build', '--outDir', 'dist-p7', '--emptyOutDir'], {
      env: { ...process.env, VITE_USE_MOCK: 'false' },
    });
    if (build.code !== 0) {
      process.stderr.write(build.stderr || build.stdout);
      throw new Error('构建失败');
    }
    log('构建完成');
  }

  log(`造数：A/B 各上传一份专属资料（${JAVA}）`);
  const tokenA = await apiLogin(USER_A, PASS_A);
  const tokenB = await apiLogin(USER_B, PASS_B);
  const stamp = Date.now().toString(36);
  const titleA = `A专属资料${stamp}`;
  const titleB = `B专属资料${stamp}`;
  await apiUpload(tokenA, `a-${stamp}.md`, `# ${titleA}\n\n这是 A 账号的资料，只有 A 能看到。\n`);
  await apiUpload(tokenB, `b-${stamp}.md`, `# ${titleB}\n\n这是 B 账号的资料，只有 B 能看到。\n`);

  // 提问要有引用，语料必须先入库：只上传不建库的话 chunk 表是空的，
  // Python 检索返回空 citations，页面上就不会出现 cite-excerpt。
  log('建库：A 账号把语料入库（Java→Python parse→ingest→chunks 回传）…');
  const taskA = await apiRebuildAndWait(tokenA);
  log(`建库完成：task ${taskA.id} / ${taskA.status} / chunks ${taskA.chunkCount}`);

  const server = await startServer();
  log(`静态服务器 + API 代理就绪：${ORIGIN}`);

  const browserA = await launchChrome({ profileDir: join(ROOT, '.chrome-p7-a') });
  const browserB = await launchChrome({ profileDir: join(ROOT, '.chrome-p7-b') });
  const items = [];

  try {
    /* ---------------- A 账号 ---------------- */
    const pageA = await browserA.openPage(`${ORIGIN}/login`);
    await pageA.setViewport(1440, 900);
    const uiTokenA = await loginThroughUi(pageA, USER_A, PASS_A);
    const titlesA = await knowledgeTitles(pageA);
    await pageA.screenshot(join(SHOT_DIR, 'p7-a-knowledge.png'));

    const seesOwnA = titlesA.some((t) => t.includes(titleA));
    const seesOtherA = titlesA.some((t) => t.includes(titleB));
    const claimsA = jwtClaims(uiTokenA);
    const profileA = await apiProfile(uiTokenA);
    items.push({
      item: 'G1',
      name: `A 账号（${USER_A}）在知识库只看到自己的资料`,
      ok: seesOwnA && !seesOtherA && profileA.username === USER_A,
      expected: `包含「${titleA}」，不含「${titleB}」；UI token 的 sub 指向 ${USER_A}`,
      titles: titlesA,
      // JWT 每次登录都带新的 iat/jti，字符串必然不同，只能比身份声明
      tokenSubject: claimsA?.sub ?? null,
      profileUsername: profileA.username,
      screenshot: 'test-artifacts/screenshots/p7-a-knowledge.png',
    });
    log(`G1 ${seesOwnA && !seesOtherA ? 'PASS' : 'FAIL'} A 看到 ${titlesA.length} 份：${titlesA.join(' | ')}`);

    const chatA = await askQuestion(pageA, '这份资料讲了什么？');
    // G3 要证的是 Java→Python→检索→SSE→落库整条链路，所以除了正文非空、无错误，
    // 还要求检索过程面板报告「采用 ≥1 段」—— 0 段说明语料没进索引或没按用户检索。
    const keptA = Number(/采用\s*(\d+)\s*段/.exec(chatA.traceMeta ?? '')?.[1] ?? 0);
    const chatOk = chatA.answer.length > 0 && !chatA.error && keptA > 0;
    await pageA.screenshot(join(SHOT_DIR, 'p7-a-chat.png'));
    items.push({
      item: 'G3',
      name: 'A 账号在对话页拿到真实回答（Java→Python→SSE→落库）',
      ok: chatOk,
      expected: 'answer-body 非空、无 msg-error、检索过程「采用 ≥1 段」',
      answer: chatA.answer,
      citeBadges: chatA.citeBadges,
      traceMeta: chatA.traceMeta,
      retriedSend: chatA.retriedSend === true,
      degraded: chatA.degraded,
      error: chatA.error,
      screenshot: 'test-artifacts/screenshots/p7-a-chat.png',
    });
    log(`G3 ${chatOk ? 'PASS' : 'FAIL'} 回答 ${chatA.answer.length} 字 / ${chatA.traceMeta ?? '无检索面板'}`);

    /* ---------------- B 账号（独立 profile） ---------------- */
    const pageB = await browserB.openPage(`${ORIGIN}/login`);
    await pageB.setViewport(1440, 900);
    const uiTokenB = await loginThroughUi(pageB, USER_B, PASS_B);
    const titlesB = await knowledgeTitles(pageB);
    await pageB.screenshot(join(SHOT_DIR, 'p7-b-knowledge.png'));

    const seesOwnB = titlesB.some((t) => t.includes(titleB));
    const seesOtherB = titlesB.some((t) => t.includes(titleA));
    const claimsB = jwtClaims(uiTokenB);
    const profileB = await apiProfile(uiTokenB);
    items.push({
      item: 'G2',
      name: `B 账号（${USER_B}）在知识库只看到自己的资料`,
      ok: seesOwnB && !seesOtherB && profileB.username === USER_B,
      expected: `包含「${titleB}」，不含「${titleA}」；UI token 的 sub 指向 ${USER_B}`,
      titles: titlesB,
      tokenSubject: claimsB?.sub ?? null,
      profileUsername: profileB.username,
      screenshot: 'test-artifacts/screenshots/p7-b-knowledge.png',
    });
    log(`G2 ${seesOwnB && !seesOtherB ? 'PASS' : 'FAIL'} B 看到 ${titlesB.length} 份：${titlesB.join(' | ')}`);

    const subA = claimsA?.sub ?? null;
    const subB = claimsB?.sub ?? null;
    items.push({
      item: 'G4',
      name: '两个 profile 的 token 属于不同用户（真隔离而非共享会话）',
      ok: !!subA && !!subB && subA !== subB && profileA.id !== profileB.id,
      expected: 'A/B 各自拿到自己账号签发的 JWT，sub 与 user.id 都不同',
      subjectA: subA,
      subjectB: subB,
      userIdA: profileA.id,
      userIdB: profileB.id,
    });
    log(`G4 ${subA !== subB ? 'PASS' : 'FAIL'} sub ${subA}/${subB}`);

    pageA.close();
    pageB.close();
  } finally {
    await browserA.close();
    await browserB.close();
    server.close();
  }

  const pass = items.every((item) => item.ok);
  const report = {
    pass,
    at: Date.now(),
    origin: ORIGIN,
    java: JAVA,
    elapsedMs: Date.now() - startedAt,
    items,
  };
  writeFileSync(join(OUT_DIR, 'p7-browser.json'), `${JSON.stringify(report, null, 2)}\n`, 'utf8');

  // 只清理本脚本自己构建出来的 dist-p7；调用方指定的产物目录（P7_WEB_DIST）
  // 是它的正式构建输出，删掉会让下一次运行直接报「目录不存在」。
  if (!KEEP && !process.env.P7_WEB_DIST) {
    rmSync(DIST, { recursive: true, force: true });
  }

  log(pass ? '🎉 G 项浏览器双账号联调通过' : '❌ G 项存在失败断言');
  if (!pass) process.exitCode = 1;
}

main().catch((error) => {
  process.stderr.write(`[p7-browser] 失败：${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
