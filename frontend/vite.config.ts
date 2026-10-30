import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';

/*
 * 代理说明：
 * - 开发态 /api 转发到 Java 业务服务（默认 8080，可用 VITE_PROXY_TARGET 覆盖）
 * - 前端永远只认识 /api/v1/**，永远不知道 /internal 的存在
 */
export default defineConfig({
  plugins: [vue()],
  base: '/',
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 4173,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    emptyOutDir: true,
    target: 'es2020',
    sourcemap: false,
  },
  test: {
    environment: 'jsdom',
    globals: false,
    include: ['test/**/*.spec.ts'],
    setupFiles: ['test/setup.ts'],
    css: false,
    restoreMocks: true,
    testTimeout: 10000,
    server: {
      deps: {
        inline: ['element-plus'],
      },
    },
  },
});
