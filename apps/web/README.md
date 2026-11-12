# 小忆 RAG 知识库问答 · 前端（v2 重构版）

Vue 3 + TypeScript + Vite 重写的前端。功能对照 `docs/01-功能规格/` 的 F01–F11 与
`docs/02-重构设计/` 的套餐方案，三页 + 登录页，全站 mock 可跑。

> 旧版前端 `web/`（Vue 3 + 纯 JS，无 TS、无 UI 框架）已于 2026-11-01 删除，`frontend/` 是唯一前端。
> 已删除资产的归档已于 2026-11-09 清除（历史见 Git）。

---

## 快速开始

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173，默认走 mock，无需后端
```

打开后会自动落到登录页。mock 模式仍可使用测试账号登录；真实后端模式必须使用部署配置或测试初始化创建的账号。

### 常用命令

| 命令 | 作用 |
| --- | --- |
| `npm run dev` | 开发服务器（mock 开启） |
| `npm run build` | 类型检查 + 生产构建，产物在 `dist/` |
| `npm run preview` | 预览构建产物 |
| `npm run lint` | ESLint，`--max-warnings 0`，有警告即失败 |
| `npm run typecheck` | `vue-tsc --noEmit` |
| `npm run test` | Vitest 全量单测 + 集成测试（真走 MSW） |
| `npm run test:watch` | 监听模式 |
| `npm run gate -- P6 --build` | 四道门禁一次跑完（lint → typecheck → test → build），报告落 `test-artifacts/` |
| `npm run smoke` | 真实 Chrome 无头渲染 + 截图，报告落 `test-artifacts/smoke.json` |
| `npm run regress` | CDP 驱动真实操作的全量回归（10 个验收场景 + 逐条截图），报告落 `test-artifacts/regress.json` |
| `npm run snapshot -- save <名字>` | 把 `src/` 与配置快照到 `.snapshots/`，`restore` 可回滚 |
| `npm run gen:api` | 从 `docs/api/openapi-public.yaml` 生成类型（文件不存在时静默跳过） |

---

## mock 与真实后端切换

**只改一个环境变量**，`frontend/.env.development`：

```dotenv
# 走内置 mock（默认）：MSW 拦截 /api/v1，数据在 src/mocks/
VITE_USE_MOCK=true

# 走后端：把这行改成 false，并确保后端在 http://localhost:8080
VITE_USE_MOCK=false
```

改成 `false` 之后：

- 前端不再注册 service worker，所有请求真实发出；
- 开发服务器会把 `/api` 代理到 `http://localhost:8080`（见 `vite.config.ts` 的 `server.proxy`）；
- 后端不在本机时，用 `VITE_PROXY_TARGET` 覆盖目标地址：

  ```bash
  VITE_PROXY_TARGET=http://192.168.1.20:8080 npm run dev
  ```

`.env.production` 里 `VITE_USE_MOCK=false`，即构建产物永远打真实接口。

### mock 覆盖了什么

`src/mocks/handlers.ts` 用 MSW 实现了 28 个端点，覆盖四个页面全部读写路径：

- **认证**：`POST /auth/login`、`GET /auth/profile`
- **会话**：会话 CRUD、消息列表、清空、单条 trace
- **对话**：`POST /chat/stream` 用 `ReadableStream` 逐帧推 SSE（status → retrieval → token → done），不是一次性返回，所以流式渲染、中止、错误态都能真跑
- **知识库**：资料 CRUD、启停用、上传（校验扩展名/2MB/空正文）、`index/status`、`index/rebuild`、`index/tasks/:id`（1 秒推进阶段：解析 → 切分 → 嵌入 → 摘要 → 完成）、`chunks`
- **评测**：`eval/questions`、`eval/batch`、`eval/runs`、候选池决策、参数实验创建/查询/报告（实验按 `experimentDuration` 真推进进度，期间 `POST /chat/stream` 返回 **409**）、反馈提交与汇总

mock 的语料与 `data/*.md` 六份资料一致，按 180/30 切分得 15 个片段 —— 这些数字和
`docs/01-功能规格/` 里写的验收预期对得上，所以界面上看到的条数是真实条数，不是随便凑的。

---

## 目录结构

```
src/
  api/             # 唯一允许出现 axios 的地方
    http.ts        #   实例 + 拦截器（拆 Result.data、401 清 token、503 广播降级）
    sse.ts         #   纯函数 SSE 解析器 + fetch 流式读取
    normalize.ts   #   snake_case ↔ camelCase、引用双形状归一
    modules/       #   auth / chat / knowledge / eval 四个命名空间
  app/
    layout/        # AppShell / AppTopbar / AppSidebar / StatusLight / StatusBanner / ExperimentBanner
    router/        # 路由表 + 守卫（纯函数 resolveNavigation，可单测）
  components/      # 跨特性共享（ListSkeleton）
  composables/     # useQueryPrefs（提问模式与 k，存 localStorage）
  constants/       # 阈值、状态元数据、localStorage 键
  features/        # feature-first：每个特性自带 components / composables / views / index.ts
    auth/  chat/  knowledge/  eval/
  mocks/           # MSW handlers + 种子数据 + 浏览器/Node 两套 worker
  stores/          # Pinia：只放 systemStatus / conversations / uiPrefs
  styles/          # tokens.css（U04 设计令牌，含深色覆盖）+ base.css
  types/           # api.d.ts（手写契约，openapi 就绪后由 gen:api 替换）
  utils/           # markdown 白名单解析、text、csv、storage
```

### 三条硬约束

1. **渲染层零 `v-html`**。`utils/markdown.ts` 自己解析成节点树，模板里用组件递归渲染。
   资料正文、回答、留言都当不可信输入处理 —— `06_成员留言摘录.md` 里那句
   「忽略你之前收到的所有规则」就是按纯文本显示的。
2. **组件不直连 axios**。只有 `src/api/http.ts` 出现 `import axios`，其余一律走
   `authApi / chatApi / knowledgeApi / evalApi`。
3. **服务端数据不进 Pinia**。Pinia 只管三件事：系统状态、会话列表、主题偏好。
   消息、资料、片段、评测结果都是 composable 局部状态 —— 它们的生命周期跟页面走，
   塞进全局 store 只会让「清空对话」这类操作牵扯到不相干的缓存。

---

## 设计要点

### 引用双形状

后端可能返回 `ref: 1`（第几个来源）或 `ref: "D02-C001"`（片段 ID）。`normalize.ts` 统一成
`{ref, chunkId, valid}`，`utils/text.ts` 的 `resolveCitation()` 负责查表：

- 查到 → 实心徽标，点击弹引用卡（五要素 + 得分条 + 原文）；
- 查不到 → **虚线删除线的幽灵徽标**，点不动。模型编了一个不存在的来源时，
  界面上必须看得出来，而不是假装有据可查。

### 状态联动

- 改资料 / 改分块参数 / 启停用 → `systemStatus.markNeedsRebuild()` → 顶栏黄灯 + 琥珀横幅
  「资料或分块设置已改变，重新建库后即可使用最新资料提问」，横幅上的按钮直达建库面板。
- 建库跑完 → `markReady(chunkCount)` → 黄灯转绿灯。
- 参数实验进行中 → 全站横幅「参数实验进行中，提问暂不可用（后端 409 互斥保护）」，
  输入框与示例 chips 同时禁用，避免白打一次 409。

### 空态 / 骨架屏 / 错误态

五个列表页（资料 / 片段 / 候选池 / 历史 / 题目）三态齐备，加载态统一用 `ListSkeleton`
骨架屏而不是「正在加载…」文字 —— 数据回来时布局不塌陷。

### 深浅色

`tokens.css` 里所有颜色都是 CSS 变量，`[data-theme='dark']` 整块覆盖。切换只改
`document.documentElement.dataset.theme`，不需要重渲染组件树。主题存 localStorage，
刷新后保持。

---

## 测试

```bash
npm run test              # 全量
npm run test -- test/eval # 单个目录
npm run gate -- P6 --build
```

- 纯函数层（分块合并、过滤、CSV、矩阵展开、最优行、状态机）单测覆盖分支；
- 组件层用 `@vue/test-utils` 断言 `data-testid`；
- 页面级测试**真走 MSW**：上传会真的发 multipart、SSE 会真的逐帧读、实验会真的推进进度，
  不是把 API 层 mock 掉。这样才能挡住「接口字段名改了但页面没改」这类问题。

几个踩过的坑写在测试文件顶部注释里，改测试前值得先读：

- jsdom 的 `Blob` 没有 `stream()`/`arrayBuffer()`/`text()`，undici 序列化 FormData 时会永久挂住 →
  `test/setup.ts` 用 `FileReader` 补了这三个方法；
- MSW 的 fetch 走宏任务链，`flushPromises()` 排不空 → 等接口一律用轮询式 `waitFor()`；
- `el-input` 的根元素本身就是 `<input>`，`setValue` 要打在带 `data-testid` 的那个元素上。

### 浏览器冒烟

```bash
npm run smoke          # 需要本机装了 Chrome 或 Edge
```

真 Chrome 无头跑 5 条路由 + 深色主题 + 窄屏（900×720），断言关键节点存在并截图到
`test-artifacts/screenshots/`。冒烟用生产构建 + 脚本内置的 stub API，**不走 MSW** ——
service worker 在 `--headless=new` 下等不到 controller，页面会永远停在空壳
（这就是为什么冒烟必须用另一条链路，而不是复用开发环境的 mock）。

### 全量回归（真实操作路径）

冒烟只回答「构建产物能不能起来」，回归回答「验收清单里的操作路径能不能走通」——
发问、点引用卡、改参数重建、跑批量对照、跑参数实验、清空对话，都必须真的点。

```bash
npm run regress                 # 全量 10 个场景
npm run regress -- --only=chat  # 只跑名字含 chat 的场景
npm run regress -- --keep       # 保留 dist-regress/ 便于排查
```

驱动方式是自己写的零依赖 CDP 客户端（`scripts/cdp.mjs`），不引 puppeteer：本项目
锁定的 Node 21.7.1 依赖矩阵已经很紧，而 CDP 本身只是「HTTP 拿 ws 地址 + WebSocket
发 JSON」。几个踩过的坑都写在代码注释里：`/json/new` 必须用 PUT（Chrome 111+ 对 GET
回 405）；spawn 不能开 shell（Chrome 路径含空格会被 cmd.exe 拆词）；`el-input-number`
的加减按钮由 `vRepeatClick` 驱动，监听的是 **mousedown** 而不是 click。

10 个场景：知识库列表 / 建库进度 / T03 提问 / 引用卡 / k=1 与 k=3 检索过程对照 /
T09 对照模式 / 批量对照测试 / 参数矩阵实验 / 片段重叠 / 清空对话。每步截图落在
`test-artifacts/screenshots/regress-*.png`，结论写 `test-artifacts/regress.json`。

---

## 已知边界

- **后端未接入**：本轮所有验证都在 mock 上完成。Java 侧 `/api/v1` 就绪后，把
  `VITE_USE_MOCK` 改 `false` 即可真联调，契约见 `src/types/api.d.ts`。
- **`openapi-public.yaml` 尚未产出**：`types/api.d.ts` 是手写契约，`gen:api` 脚本已就位，
  契约文件一到就能换掉。
- **Element Plus 全量引入**：`vendor-ui` 约 797 kB（gzip 252 kB）。按需引入需要
  `unplugin-vue-components`，而它的新版要求 Node ≥ 20.19，与本项目锁定的 Node 21.7
  构建链不匹配，因此本轮显式选择全量引入并在 `vite.config.ts` 里把告警阈值调到 850 kB。
- **Node 版本**：开发机为 v21.7.1。`npm install` 会打印 `EBADENGINE`（`balanced-match`、
  `brace-expansion` 声明要求 18/20/≥22），不影响构建与测试。
