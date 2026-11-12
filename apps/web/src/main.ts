import { createApp } from 'vue';
import ElementPlus from 'element-plus';
import zhCn from 'element-plus/es/locale/lang/zh-cn';
import 'element-plus/dist/index.css';
import { createPinia } from 'pinia';
import App from './App.vue';
import router from './app/router';
import './styles/tokens.css';
import './styles/base.css';

async function bootstrap(): Promise<void> {
  // Mock 开关：只改 .env 一行即可在 mock / 真实后端之间切换
  if (import.meta.env.VITE_USE_MOCK === 'true') {
    const { startMockWorker } = await import('./mocks/browser');
    await startMockWorker();
  }

  const app = createApp(App);
  app.use(createPinia());
  app.use(router);
  app.use(ElementPlus, { locale: zhCn });
  app.mount('#app');
}

void bootstrap();
