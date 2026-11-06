import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import pluginVue from 'eslint-plugin-vue';
import vueParser from 'vue-eslint-parser';
import prettier from 'eslint-config-prettier';

export default tseslint.config(
  {
    ignores: [
      // 构建产物一律不查：dist-regress / dist-smoke 是 smoke.mjs 与 regress.mjs
      // 临时产出的真实构建目录，里面全是压缩后的第三方代码，
      // 一旦漏进来就是几千条 no-unused-expressions（实测 3603 条）。
      'dist/**',
      'dist-*/**',
      'node_modules/**',
      'coverage/**',
      'test-artifacts/**',
      '.snapshots/**',
      'public/**',
      // Chrome 用户数据目录（smoke/regress 的 --user-data-dir），里面有扩展与缓存脚本
      '.chrome-*/**',
      // 契约生成物：由 npm run gen:api 从 docs/api/openapi-public.yaml 产出，
      // 格式与注释都不受本仓库风格约束（它自带 eslint-disable 头，反而会报 unused directive）。
      'src/types/api.generated.ts',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parser: vueParser,
      parserOptions: {
        parser: tseslint.parser,
        ecmaVersion: 'latest',
        sourceType: 'module',
        extraFileExtensions: ['.vue'],
      },
    },
  },
  {
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
    rules: {
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      'no-debugger': 'error',
      'prefer-const': 'error',
      eqeqeq: ['error', 'smart'],
      'vue/multi-word-component-names': 'off',
      'vue/no-v-html': 'error',
      'vue/require-default-prop': 'off',
      'vue/attributes-order': 'off',
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/html-self-closing': 'off',
      'vue/html-indent': 'off',
      'vue/html-closing-bracket-newline': 'off',
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { prefer: 'type-imports', fixStyle: 'inline-type-imports' },
      ],
    },
  },
  {
    files: ['scripts/**/*.mjs', 'test/**/*.ts'],
    rules: {
      'no-console': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
  prettier,
);
