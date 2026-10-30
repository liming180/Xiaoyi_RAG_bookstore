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
    /*
     * Element Plus 全量引入后主包会超过 500 kB 触发 rollup 体积告警。
     * 这里按「框架 / 组件库 / 业务」三刀切开：
     *  - vendor-vue：vue 全家桶，几乎不变，长期缓存
     *  - vendor-ui：element-plus，升级才变
     *  - 其余进各路由 chunk
     */
    /*
     * Element Plus 全量引入后 UI 包约 794 kB（min）/ 251 kB（gzip），
     * 超过 Vite 默认 500 kB 阈值属预期，不是漏配：
     *  - 全量引入是本轮显式决策（见 docs/02-重构设计/03_前端开发提示词.md P1-A）
     *  - 按需引入需要 unplugin-vue-components，与锁定的构建链版本不匹配
     * 因此把阈值抬到实测值之上并在此记录真实体积，build 保持零告警。
     * 实测体积写入 test-artifacts/build-size.json（P6 阶段复核）。
     */
    chunkSizeWarningLimit: 850,
    rollupOptions: {
      output: {
        manualChunks(id: string): string | undefined {
          if (!id.includes('node_modules')) return undefined;
          if (/node_modules[\\/](vue|vue-router|pinia|@vue)[\\/]/.test(id)) return 'vendor-vue';
          if (/node_modules[\\/](element-plus|@element-plus)[\\/]/.test(id)) return 'vendor-ui';
          return 'vendor';
        },
      },
    },
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
