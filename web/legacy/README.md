# web/legacy —— 原生 JS 版前端（只作对照保留，不参与运行）

Vue 3 迁移前的三件套就放在这里，保留原因是：

1. **验收对照**：`docs/04-前端设计/` 里的文案、类名、行号都直接引用这几个文件，删掉就查不到出处；
2. **回滚**：万一 Vue 版本出问题，把这三个文件拷回 `web/` 并把 `app/settings.py` 的
   `WEB_DIST`/`WEB_ENTRY` 指回 `WEB_DIR`，就能退回原生版本。

| 文件 | 行数 | 作用 |
| --- | --- | --- |
| `index.html` | 200 | 页面骨架，侧栏 4 个面板 + 主区 4 个视图 + 输入区 |
| `app.js` | 657 | 全部前端逻辑：`api()` 封装、渲染函数、事件绑定、轮询 |
| `styles.css` | 610 | 设计令牌与全部样式（Vue 版拆成 4 个 css 原样搬走） |

**运行时不读取本目录**。`app/api.py` 只服务 `web/dist`，`vite.config.js` 也只处理 `web/src`。
原始备份另存在 `%TEMP%\web_backup_plain\`（临时目录，重启可能被清理，长期保留靠本目录）。

## 与 Vue 版的对应关系

| 旧文件位置 | 新文件 |
| --- | --- |
| `app.js:29` `api()` | `src/api.js` |
| `app.js:50` `linkCitations()` | `src/utils/text.js` `answerNodes()` |
| `app.js:65` `highlight()` | `src/utils/text.js` `highlightSegments()` |
| `app.js:80` `renderStatus()` | `src/store.js` `kbBadge()` + `components/TopBar.vue` |
| `app.js:132` `renderIndexHint()` | `src/store.js` `indexHint()` + `components/ChunkSettings.vue` |
| `app.js:157` `renderDocs()` | `components/DocList.vue` |
| `app.js:234` `appendTurn()` | `src/store.js` `actions.send()` + `components/ChatTurn.vue` |
| `app.js:247` `renderAnswer()` | `components/AnswerBlock.vue` |
| `app.js:289` `renderCards()` | `components/SourceCard.vue` |
| `app.js:357` `refreshTraceView()` | `components/views/TraceView.vue` |
| `app.js:394` `loadChunks()` | `components/views/ChunksView.vue` |
| `app.js:419` `renderBatch()` | `components/views/BatchView.vue` |
| `app.js:456` `pollBatch()` | `src/composables/usePolling.js` |
| `app.js:490` `buildIndex()` | `src/store.js` `actions.buildIndex()` |
| `styles.css:1-20` | `src/styles/tokens.css` |
| `styles.css:22-354` `:518-610` | `src/styles/base.css` |
| `styles.css:356-490` | `src/styles/chat.css` |
| `styles.css:492-516` | `src/styles/table.css` |
