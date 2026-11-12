import { afterAll, afterEach, beforeAll, vi } from 'vitest';
import { config } from '@vue/test-utils';
import { server } from '@/mocks/node';

/* ------------------------------------------------ jsdom 缺失的浏览器 API */

if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  });
}

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
if (!('ResizeObserver' in window)) {
  Object.defineProperty(window, 'ResizeObserver', { writable: true, value: ResizeObserverStub });
}

class IntersectionObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
  takeRecords(): [] {
    return [];
  }
}
if (!('IntersectionObserver' in window)) {
  Object.defineProperty(window, 'IntersectionObserver', {
    writable: true,
    value: IntersectionObserverStub,
  });
}

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn();
}

/**
 * jsdom 的 Blob / File 没有 stream() / arrayBuffer() / text()。
 *
 * 这会让「multipart 上传」在测试里永久挂死：undici（MSW 底层）序列化 FormData 时
 * 对每个 Blob 调 blob.stream()，拿到 undefined 后既不 resolve 也不 reject，
 * 于是 handler 里的 request.formData() 永远不返回。真实浏览器原生带这三个方法，
 * 所以这是纯测试环境的补丁，生产代码一行都不用改。
 *
 * 用 FileReader 实现 —— jsdom 的 FileReader 能正常读取 jsdom 的 File（实测可用）。
 */
function readBlobAsArrayBuffer(blob: Blob): Promise<ArrayBuffer> {
  return new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error ?? new Error('FileReader 读取失败'));
    reader.readAsArrayBuffer(blob);
  });
}

const blobProto = Blob.prototype as Blob & {
  arrayBuffer?: () => Promise<ArrayBuffer>;
  text?: () => Promise<string>;
  stream?: () => ReadableStream<Uint8Array>;
};

if (typeof blobProto.arrayBuffer !== 'function') {
  Object.defineProperty(blobProto, 'arrayBuffer', {
    writable: true,
    configurable: true,
    value(this: Blob): Promise<ArrayBuffer> {
      return readBlobAsArrayBuffer(this);
    },
  });
}

if (typeof blobProto.text !== 'function') {
  Object.defineProperty(blobProto, 'text', {
    writable: true,
    configurable: true,
    value(this: Blob): Promise<string> {
      return readBlobAsArrayBuffer(this).then((buf) => new TextDecoder().decode(buf));
    },
  });
}

if (typeof blobProto.stream !== 'function') {
  Object.defineProperty(blobProto, 'stream', {
    writable: true,
    configurable: true,
    value(this: Blob): ReadableStream<Uint8Array> {
      // 箭头函数里 this 走词法作用域，指向下面这个 Blob 实例
      return new ReadableStream<Uint8Array>({
        start: async (controller) => {
          try {
            const buf = await readBlobAsArrayBuffer(this);
            controller.enqueue(new Uint8Array(buf));
            controller.close();
          } catch (error) {
            controller.error(error);
          }
        },
      });
    },
  });
}

if (!('scrollTo' in window)) {
  Object.defineProperty(window, 'scrollTo', { writable: true, value: vi.fn() });
}

/**
 * jsdom 没有实现 URL.createObjectURL / revokeObjectURL。
 * CSV 导出会走 `createObjectURL` + `<a download>`，缺了这两个方法会直接抛错，
 * 所以补成可断言的桩（测试里可以 `expect(URL.createObjectURL).toHaveBeenCalled()`）。
 */
if (typeof URL.createObjectURL !== 'function') {
  Object.defineProperty(URL, 'createObjectURL', { writable: true, value: vi.fn(() => 'blob:mock') });
}
if (typeof URL.revokeObjectURL !== 'function') {
  Object.defineProperty(URL, 'revokeObjectURL', { writable: true, value: vi.fn() });
}

/**
 * jsdom 不会真的导航到 `blob:` 地址，导出用的 `<a download>` 一被 click
 * 就会往 stderr 打一条 `Not implemented: navigation (except hash changes)`。
 * 只拦带 `download` 属性的链接：普通链接（RouterLink 之类）照旧走 jsdom 的逻辑，
 * 否则会连带影响其它用例里的路由跳转。
 */
const anchorProto = HTMLAnchorElement.prototype;
const nativeAnchorClick = anchorProto.click;
Object.defineProperty(anchorProto, 'click', {
  writable: true,
  configurable: true,
  value(this: HTMLAnchorElement): void {
    if (this.hasAttribute('download')) return;
    nativeAnchorClick.call(this);
  },
});

/* ------------------------------------------------------------ MSW 生命周期 */

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' });
});

afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
});

afterAll(() => {
  server.close();
});

/* ------------------------------------------------------------ 全局桩组件 */

config.global.stubs = {};
