/**
 * 极简 Chrome DevTools Protocol 客户端（零依赖）。
 *
 * 为什么需要它：
 * `chrome --dump-dom` 只能拿到「页面加载完那一瞬间」的 DOM，点不了按钮、输不了文字。
 * 而 P6 的回归验收项（T03 带引用回答、T09 两模式对照、检索过程展开、k=1 vs k=3）
 * 都必须先真的发一次问、再点开某个控件，才能截到有意义的图。
 *
 * 为什么不用 puppeteer/playwright：
 * 本项目锁定的 Node 是 v21.7.1，装新依赖要重新过一遍 EBADENGINE 与版本矩阵；
 * 而 CDP 本身就是「HTTP 拿 ws 地址 + WebSocket 发 JSON」，用 Node 内建的
 * http/net/crypto 一百多行就能实现，不值得为它引入一个 300MB 的浏览器包。
 *
 * 本文件只做三件事：启动 Chrome、建立 WebSocket 连接、收发 CDP 命令。
 * 页面操作语义（点击什么、等什么）留给调用方。
 */
import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync, readFileSync, rmSync } from 'node:fs';
import { request as httpRequest } from 'node:http';
import { join } from 'node:path';

/* --------------------------------------------------------------- WebSocket */

/**
 * 建立 WebSocket 连接。
 *
 * 只实现 CDP 实际用到的子集：文本帧、分片重组、ping/pong。
 * 不做扩展协商、不做压缩 —— Chrome 的调试端点默认也不启用这两者。
 */
function wsConnect(wsUrl, onClose) {
  return new Promise((resolve, reject) => {
    const url = new URL(wsUrl);
    const req = httpRequest({
      host: url.hostname,
      port: url.port,
      path: `${url.pathname}${url.search}`,
      headers: {
        Connection: 'Upgrade',
        Upgrade: 'websocket',
        'Sec-WebSocket-Key': randomBytes(16).toString('base64'),
        'Sec-WebSocket-Version': '13',
      },
    });

    req.on('upgrade', (res, socket, head) => {
      if (res.statusCode !== 101) {
        reject(new Error(`WebSocket 握手失败：HTTP ${res.statusCode}`));
        socket.destroy();
        return;
      }

      let buffer = head && head.length > 0 ? Buffer.from(head) : Buffer.alloc(0);
      let fragments = [];
      const listeners = new Set();
      // 连接断掉后所有挂起的命令都不会再有回包。必须显式通知调用方，
      // 否则每条命令只能干等到超时，看不出「连接已死」这个真实原因。
      const notifyClosed = (reason) => {
        if (closed) return;
        closed = true;
        onClose?.(reason);
      };
      let closed = false;

      const emit = (text) => {
        for (const listener of listeners) listener(text);
      };

      const handleFrame = (fin, opcode, payload) => {
        if (opcode === 0x9) {
          socket.write(encodeFrame(payload, 0xa)); // ping → pong
          return;
        }
        if (opcode === 0x8) {
          socket.end();
          notifyClosed('服务端发来 close 帧');
          return;
        }
        if (opcode === 0xa) return; // pong 忽略

        fragments.push(payload);
        if (!fin) return;
        const text = Buffer.concat(fragments).toString('utf8');
        fragments = [];
        emit(text);
      };

      const pump = () => {
        for (;;) {
          if (buffer.length < 2) return;
          const first = buffer[0];
          const second = buffer[1];
          const fin = (first & 0x80) !== 0;
          const opcode = first & 0x0f;
          const masked = (second & 0x80) !== 0;
          let length = second & 0x7f;
          let offset = 2;

          if (length === 126) {
            if (buffer.length < offset + 2) return;
            length = buffer.readUInt16BE(offset);
            offset += 2;
          } else if (length === 127) {
            if (buffer.length < offset + 8) return;
            const big = buffer.readBigUInt64BE(offset);
            if (big > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error('WebSocket 帧过大');
            length = Number(big);
            offset += 8;
          }

          let mask = null;
          if (masked) {
            if (buffer.length < offset + 4) return;
            mask = buffer.subarray(offset, offset + 4);
            offset += 4;
          }

          if (buffer.length < offset + length) return;
          let payload = buffer.subarray(offset, offset + length);
          if (mask) {
            const unmasked = Buffer.allocUnsafe(payload.length);
            for (let i = 0; i < payload.length; i += 1) unmasked[i] = payload[i] ^ mask[i % 4];
            payload = unmasked;
          }
          buffer = buffer.subarray(offset + length);
          handleFrame(fin, opcode, payload);
        }
      };

      socket.on('data', (chunk) => {
        buffer = Buffer.concat([buffer, chunk]);
        try {
          pump();
        } catch (error) {
          reject(error);
        }
      });
      socket.on('error', (error) => {
        notifyClosed(`WebSocket 错误：${error.message}`);
        reject(error);
      });
      socket.on('end', () => notifyClosed('WebSocket 对端关闭'));
      socket.on('close', () => notifyClosed('WebSocket 连接关闭'));

      resolve({
        send(text) {
          socket.write(encodeFrame(Buffer.from(text, 'utf8'), 0x1));
        },
        onMessage(listener) {
          listeners.add(listener);
          return () => listeners.delete(listener);
        },
        close() {
          socket.destroy();
        },
      });
    });

    req.on('error', reject);
    req.end();
  });
}

/** 客户端发出的帧必须加掩码（RFC 6455 §5.3），否则 Chrome 直接断开。 */
function encodeFrame(payload, opcode) {
  const mask = randomBytes(4);
  const length = payload.length;
  let header;

  if (length < 126) {
    header = Buffer.alloc(2);
    header[1] = 0x80 | length;
  } else if (length < 65536) {
    header = Buffer.alloc(4);
    header[1] = 0x80 | 126;
    header.writeUInt16BE(length, 2);
  } else {
    header = Buffer.alloc(10);
    header[1] = 0x80 | 127;
    header.writeBigUInt64BE(BigInt(length), 2);
  }
  header[0] = 0x80 | opcode;

  const masked = Buffer.allocUnsafe(length);
  for (let i = 0; i < length; i += 1) masked[i] = payload[i] ^ mask[i % 4];
  return Buffer.concat([header, mask, masked]);
}

/* ------------------------------------------------------------------- Chrome */

const CHROME_CANDIDATES = [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  `${process.env.LOCALAPPDATA ?? ''}/Google/Chrome/Application/chrome.exe`,
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
];

export function findChrome() {
  for (const candidate of CHROME_CANDIDATES) {
    if (candidate && existsSync(candidate)) return candidate;
  }
  return null;
}

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

/**
 * 启动带调试端口的 headless Chrome，返回 CDP 会话。
 *
 * `--remote-debugging-port=0` 让系统分配端口，实际端口写在 user-data-dir 下的
 * `DevToolsActivePort` 文件里（第一行端口，第二行 ws 路径）。这样并行跑多个
 * 实例也不会撞端口。
 */
export async function launchChrome({ profileDir, windowSize = '1600,950' }) {
  const chrome = findChrome();
  if (!chrome) throw new Error('未找到 Chrome/Edge');

  // 上一次被强杀的 Chrome 会留下被 Crashpad 占用的 profile，
  // 直接 rmSync 会抛 EBUSY 把新一轮回归带崩，所以吞掉并重试。
  for (let i = 0; i < 5; i += 1) {
    try {
      rmSync(profileDir, { recursive: true, force: true });
      break;
    } catch {
      await sleep(200);
    }
  }

  const child = spawn(
    chrome,
    [
      '--headless=new',
      '--disable-gpu',
      '--hide-scrollbars',
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-extensions',
      '--disable-dev-shm-usage',
      '--remote-debugging-port=0',
      `--window-size=${windowSize}`,
      `--user-data-dir=${profileDir}`,
      'about:blank',
    ],
    // 不开 shell：Chrome 安装路径含空格，经 cmd.exe 转发会被拆词
    { shell: false, stdio: ['ignore', 'ignore', 'ignore'] },
  );

  const portFile = join(profileDir, 'DevToolsActivePort');
  let port = null;
  for (let i = 0; i < 100; i += 1) {
    if (existsSync(portFile)) {
      const line = readFileSync(portFile, 'utf8').split('\n')[0]?.trim();
      if (line && Number(line) > 0) {
        port = Number(line);
        break;
      }
    }
    await sleep(100);
  }
  if (!port) {
    child.kill();
    throw new Error('Chrome 调试端口未就绪');
  }

  const endpoint = `http://127.0.0.1:${port}`;

  const close = async () => {
    try {
      await fetch(`${endpoint}/json/close/${current.targetId}`);
    } catch {
      // 关不掉也无所谓，进程会被 kill
    }
    child.kill();
    await sleep(300);
    // Windows 上 Chrome 退出后 Crashpad 句柄还会占用几百毫秒，
    // 直接 rmSync 会抛 EBUSY/EPERM 把整轮回归带崩，所以吞掉并重试几次。
    for (let i = 0; i < 5; i += 1) {
      try {
        rmSync(profileDir, { recursive: true, force: true });
        return;
      } catch {
        await sleep(200);
      }
    }
  };

  let current = null;

  /**
   * 新建一个标签页并连上它的调试端点。
   *
   * 注意 Chrome 从 111 起 `/json/new` 必须是 PUT，用 GET 会回 405。
   */
  const openPage = async (url = 'about:blank') => {
    const res = await fetch(`${endpoint}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' });
    const target = await res.json();

    let seq = 0;
    const pending = new Map();
    const eventHandlers = new Map();

    // 连接一断，挂起的命令立刻以「连接已关闭」失败，而不是各自干等到 30s 超时。
    const ws = await wsConnect(target.webSocketDebuggerUrl, (reason) => {
      for (const [id, waiter] of pending) {
        pending.delete(id);
        waiter.reject(new Error(`CDP 连接已关闭（${reason}），${waiter.method} 无回包`));
      }
    });

    ws.onMessage((text) => {
      let message;
      try {
        message = JSON.parse(text);
      } catch {
        return;
      }
      if (message.id !== undefined) {
        const waiter = pending.get(message.id);
        if (!waiter) return;
        pending.delete(message.id);
        if (message.error) waiter.reject(new Error(`${waiter.method}: ${message.error.message}`));
        else waiter.resolve(message.result);
        return;
      }
      const handlers = eventHandlers.get(message.method);
      if (handlers) for (const handler of handlers) handler(message.params);
    });

    const send = (method, params = {}, timeoutMs = 30000) =>
      new Promise((resolve, reject) => {
        seq += 1;
        const id = seq;
        // 每条命令都带超时：页面崩溃/标签页被关时 CDP 不会再回包，
        // 没有超时会让整个回归脚本静默挂死（实测挂过 8 分钟无输出）。
        const timer = setTimeout(() => {
          pending.delete(id);
          reject(new Error(`${method} 超时（${timeoutMs}ms 未收到回包）`));
        }, timeoutMs);
        pending.set(id, {
          resolve: (value) => {
            clearTimeout(timer);
            resolve(value);
          },
          reject: (error) => {
            clearTimeout(timer);
            reject(error);
          },
          method,
        });
        ws.send(JSON.stringify({ id, method, params }));
      });

    const on = (method, handler) => {
      if (!eventHandlers.has(method)) eventHandlers.set(method, new Set());
      eventHandlers.get(method).add(handler);
      return () => eventHandlers.get(method)?.delete(handler);
    };

    await send('Page.enable');
    await send('Runtime.enable');

    /** 导航并等 load 事件；超时兜底返回，避免个别资源拖死整个脚本。 */
    const goto = async (url, timeoutMs = 20000) => {
      const loaded = new Promise((resolve) => {
        const off = on('Page.loadEventFired', () => {
          off();
          resolve();
        });
      });
      await send('Page.navigate', { url });
      await Promise.race([loaded, sleep(timeoutMs)]);
    };

    /** 在页面里执行一段表达式，返回它的值（必须可 JSON 序列化）。 */
    const evaluate = async (expression) => {
      const result = await send('Runtime.evaluate', {
        expression,
        awaitPromise: true,
        returnByValue: true,
      });
      if (result.exceptionDetails) {
        throw new Error(
          `页面脚本异常：${result.exceptionDetails.exception?.description ?? result.exceptionDetails.text}`,
        );
      }
      return result.result?.value;
    };

    /** 轮询式等待，直到表达式返回真值；比固定 sleep 稳，也比 MutationObserver 简单。 */
    const waitFor = async (expression, { timeoutMs = 15000, intervalMs = 100, label = '' } = {}) => {
      const deadline = Date.now() + timeoutMs;
      for (;;) {
        if (await evaluate(expression)) return true;
        if (Date.now() > deadline) throw new Error(`等待超时${label ? `：${label}` : ''}`);
        await sleep(intervalMs);
      }
    };

    const click = async (selector) => {
      const found = await evaluate(`(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) return false;
        el.click();
        return true;
      })()`);
      if (!found) throw new Error(`点击失败，找不到元素：${selector}`);
    };

    /**
     * 往输入框里写文字。
     *
     * 直接改 value 不会触发 Vue 的 v-model（它监听 input 事件），
     * 所以这里手动派发一次冒泡的 InputEvent。
     */
    const type = async (selector, text) => {
      const done = await evaluate(`(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) return false;
        const proto = el instanceof HTMLTextAreaElement
          ? HTMLTextAreaElement.prototype
          : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(text)});
        el.dispatchEvent(new Event('input', { bubbles: true }));
        return true;
      })()`);
      if (!done) throw new Error(`输入失败，找不到元素：${selector}`);
    };

    const screenshot = async (file) => {
      const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
      const { writeFileSync, mkdirSync } = await import('node:fs');
      const { dirname } = await import('node:path');
      mkdirSync(dirname(file), { recursive: true });
      writeFileSync(file, Buffer.from(data, 'base64'));
      return true;
    };

    /** 视口尺寸覆盖：窄屏断言走这条，比重启浏览器快得多。 */
    const setViewport = async (width, height) => {
      await send('Emulation.setDeviceMetricsOverride', {
        width,
        height,
        deviceScaleFactor: 1,
        mobile: false,
      });
    };

    const page = {
      targetId: target.id,
      send,
      on,
      goto,
      evaluate,
      waitFor,
      click,
      type,
      screenshot,
      setViewport,
      close() {
        ws.close();
      },
    };
    current = page;
    return page;
  };

  return { endpoint, openPage, close };
}
