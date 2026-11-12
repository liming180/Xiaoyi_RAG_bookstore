import { setupWorker } from 'msw/browser';
import { handlers } from './handlers';

/** 浏览器侧 MSW：仅当 VITE_USE_MOCK=true 时启用 */
export const worker = setupWorker(...handlers);

export async function startMockWorker(): Promise<void> {
  await worker.start({
    onUnhandledRequest: 'bypass',
    quiet: true,
    serviceWorker: { url: '/mockServiceWorker.js' },
  });
}
