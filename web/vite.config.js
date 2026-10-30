import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

/*
 * base 切换的原因：
 * - dev  : Vite 自己起 5173，页面根路径是 /，资源也要按 / 取。
 * - build: 产物由 FastAPI 的 /static 挂载托管（app/api.py 的 StaticFiles），
 *          所以资源必须带 /static/ 前缀，否则 dist/index.html 里的 <script> 会 404。
 */
export default defineConfig(({ command }) => ({
  plugins: [vue()],
  base: command === 'build' ? '/static/' : '/',
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    emptyOutDir: true,
    target: 'es2020',
  },
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      // 开发时把 /api 转给本地 FastAPI（py -3.12 -X utf8 -m app.api，默认 8765）
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: false,
      },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['test/**/*.spec.js'],
    globals: false,
  },
}));
