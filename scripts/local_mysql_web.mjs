/* 本机 MySQL 模式的前端静态服务 + /api 反代；不启动 Vite/MSW，不依赖 Docker。 */
import { createServer } from 'node:http';
import { request as httpRequest } from 'node:http';
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { extname, join, normalize, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('..', import.meta.url)));
const DIST = resolve(ROOT, 'frontend', 'dist');
const PORT = Number(process.env.P7_WEB_PORT ?? 4173);
const JAVA = process.env.P7_JAVA ?? 'http://127.0.0.1:8080';
const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.ico': 'image/x-icon',
  '.woff': 'font/woff', '.woff2': 'font/woff2',
};
const ARTIFACTS = resolve(ROOT, 'test-artifacts');
const PIDS = resolve(ARTIFACTS, 'local-mysql-state.json');
mkdirSync(ARTIFACTS, { recursive: true });
let state = {};
try { state = JSON.parse(readFileSync(PIDS, 'utf8')); } catch { /* 尚无状态 */ }
writeFileSync(PIDS, JSON.stringify({ ...state, web: process.pid }, null, 2));

const server = createServer((req, res) => {
  if (req.url?.startsWith('/api/')) {
    const target = new URL(req.url, JAVA);
    const proxy = httpRequest({
      hostname: target.hostname, port: target.port,
      path: `${target.pathname}${target.search}`, method: req.method,
      headers: { ...req.headers, host: target.host },
    }, (upstream) => {
      res.writeHead(upstream.statusCode ?? 502, upstream.headers);
      upstream.pipe(res);
    });
    proxy.on('error', (error) => {
      res.writeHead(502, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end(`代理失败：${error.message}`);
    });
    req.pipe(proxy);
    return;
  }
  const pathname = decodeURIComponent((req.url ?? '/').split('?')[0]);
  const relative = normalize(pathname).replace(/^([/\\])+/, '');
  let file = resolve(DIST, relative);
  if (file !== DIST && !file.startsWith(DIST + sep)) {
    res.writeHead(403); res.end('Forbidden'); return;
  }
  if (pathname === '/' || !existsSync(file) || !statSync(file).isFile()) {
    file = join(DIST, 'index.html');
  }
  if (!existsSync(file)) {
    res.writeHead(503, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('缺 apps/web/dist：先构建前端。'); return;
  }
  res.writeHead(200, { 'Content-Type': MIME[extname(file)] ?? 'application/octet-stream' });
  res.end(readFileSync(file));
});
server.on('error', (error) => { console.error(`[local-mysql-web] ${error.message}`); process.exitCode = 1; });
server.listen(PORT, '127.0.0.1', () => {
  console.log(`[local-mysql-web] http://127.0.0.1:${PORT} -> ${JAVA} (dist=${DIST})`);
});
function close() { server.close(() => process.exit(0)); }
process.on('SIGINT', close);
process.on('SIGTERM', close);
