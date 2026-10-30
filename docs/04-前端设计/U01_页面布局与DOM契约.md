# U01 页面布局与 DOM 契约

> **代码锚点**：`web/src/App.vue:27-41`、`web/src/components/AppSidebar.vue:8-19`、`web/src/components/TopBar.vue:24-40`、`web/src/styles/base.css:1-443`、`web/legacy/index.html:1-200`（旧版 id 对照）
> **最后核对**：2026-10-30 实测（浏览器 0 console error；`.view` 4 个常驻 DOM，用 `v-show` 切换）

## 一、整体骨架

```
┌──────────────────────────────────────────────────────────────────────────┐
│ .app  display:grid; grid-template-columns:340px minmax(0,1fr); 100vh     │
├────────────────────┬─────────────────────────────────────────────────────┤
│ .sidebar           │ .main  display:flex; flex-direction:column           │
│  ├ .brand          │  ├ .topbar   tabs(4) + .status-line                  │
│  │   .brand-mark   │  ├ .notice   stale 时显示                            │
│  │   h1            │  ├ .view#chat    ← v-show state.view==='chat'        │
│  │   .brand-sub    │  ├ .view#trace   ← v-show state.view==='trace'       │
│  ├ .panel DocList  │  ├ .view#chunks  ← v-show state.view==='chunks'      │
│  ├ .panel ChunkSet │  ├ .view#batch   ← v-show state.view==='batch'       │
│  ├ .panel Retrieval│  └ .composer     ← v-show state.view==='chat'        │
│  └ .panel ModelSt  │                                                      │
└────────────────────┴─────────────────────────────────────────────────────┘
                                          .toast（fixed，全局唯一）
```

`web/src/App.vue:27-41` 是唯一决定这个结构的文件：

```html
<div class="app">
  <AppSidebar />
  <div class="main">
    <TopBar />
    <NoticeBar />
    <ChatView   v-show="state.view === 'chat'" />
    <TraceView  v-show="state.view === 'trace'" />
    <ChunksView v-show="state.view === 'chunks'" />
    <BatchView  v-show="state.view === 'batch'" />
    <Composer   v-show="state.view === 'chat'" />
  </div>
  <ToastHost />
</div>
```

## 二、`v-show` 而不是 `v-if` 的三个后果

**① 4 个视图的 DOM 始终存在**。用 Playwright 抓元素时必须限定作用域：

```python
# 错：会数到 4 张表的所有 tr
page.locator("tbody tr").count()

# 对：先锁定视图再数
page.locator(".view").nth(1).locator("tbody tr").count()   # 第 1 个 .view 是 trace
```

视图在 DOM 中的固定顺序（`App.vue` 里 `v-show` 的书写顺序）：
`0 = ChatView`、`1 = TraceView`、`2 = ChunksView`、`3 = BatchView`。

**② 视图内的 `onMounted` 只跑一次**。所以 `TraceView`/`ChunksView`/`BatchView` 都额外
`watch(() => state.view, ...)` 在切回来时刷新：

```js
// web/src/components/views/ChunksView.vue:30-31
onMounted(load);
watch(() => state.view, (view) => { if (view === 'chunks') load(); });
```

**③ 输入区随视图显隐**。`Composer` 只在 chat 视图出现，切到其他 tab 时输入框消失，
`textarea.question` 的 `isVisible()` 返回 `false`——`web/test/app.spec.js` 就是靠这个断言。

## 三、旧版 DOM id 契约 → 新版 class 契约

旧版 `web/legacy/index.html` 用 30 多个 id 直接操作 DOM。新版全部改为 class + 组件，
但**语义一一对应**，改造时逐条核对过：

### 3.1 侧栏

| 旧 id | 新位置 | 新选择器 | 说明 |
| --- | --- | --- | --- |
| `#docCount` | `DocList.vue:61` | `.panel-head .badge` | `{{ state.docs.length }} 份资料` |
| `#docList` | `DocList.vue:64` | `.doc-list` | 容器 |
| （无） | `DocList.vue:66-83` | `.doc-item[data-name]` | 每条资料，`data-name` 放文件名 |
| （无） | `DocList.vue:73-80` | `.doc-main / .doc-name / .doc-meta` | 名称 + 字数 + 片段数 + 未核实徽章 |
| （无） | `DocList.vue:82` | `.icon-btn` | 删除按钮 `✕` |
| `#dropZone` | `DocList.vue:86-95` | `.drop`（`.hot` 为拖入态） | 点击触发文件选择 |
| `#fileInput` | `DocList.vue:96-103` | `input[type=file][accept=".md,.txt"][multiple][hidden]` | 用 `ref` 拿，不用 id |
| `#chunkSize` | `ChunkSettings.vue:65` | `input#chunkSize` | **保留 id**（label for 需要） |
| `#chunkOverlap` | `ChunkSettings.vue:69` | `input#chunkOverlap` | 同上 |
| `#btnIndex` | `ChunkSettings.vue:72` | `.btn.primary.block` | 文案 `重新建库` / `正在建库…` |
| `#indexBar` | `ChunkSettings.vue:76-78` | `.progress > i` | `style.width` 由 `indexHint().bar` 给 |
| `#indexHint` | `ChunkSettings.vue:79` | `.hint` | 建库四态文案 |
| （新增） | `ChunkSettings.vue:80` | `.hint.warn-text` | **`dirty` 提示**，旧版没有 |
| `#kRange` | `RetrievalSettings.vue:30-38` | `input#kRange[type=range]` | min/max 取自 `status.k_range` |
| `#kBadge` | `RetrievalSettings.vue:25` | `.panel-head .badge` | `k = {{ state.k }}` |
| `#modeSelect` | `RetrievalSettings.vue:43-47` | `select#modeSelect` | rag / direct / both |
| `#btnNew` | `RetrievalSettings.vue:50` | `.btn.block` | 文案 `清空对话` |
| `#sessionHint` | `RetrievalSettings.vue:51` | `.hint` | `会话 {{ sessionId }}` |
| `#providerBadge` | `ModelStatus.vue:39` | `.panel-head .badge`（`.warn` 时为 mock） | `离线模拟` / `真实接口` |
| `#modelHint` | `ModelStatus.vue:42` | `.hint` | mock / real 两种文案 |
| `#chatKey` | `ModelStatus.vue:46` | `input#chatKey[type=password]` | — |
| `#embedKey` | `ModelStatus.vue:50` | `input#embedKey[type=password]` | — |
| `#btnKeys` | `ModelStatus.vue:52` | `.btn.block` | 文案 `应用密钥` |

### 3.2 主区

| 旧 id | 新位置 | 新选择器 | 说明 |
| --- | --- | --- | --- |
| `#kbBadge` | `TopBar.vue:37` | `.status-line > span:first-child` | `kbBadge()` 给的 cls + text |
| `#statusText` | `TopBar.vue:38` | `.status-line > span:last-child` | `资料 6 份 · 分块 180/30` |
| `.tab[data-view]` | `TopBar.vue:27-34` | `.tab[data-view]`（`.active` 为当前） | **保留 `data-view`**，Playwright 靠它点 |
| `#notice` | `NoticeBar.vue:20` | `.notice`（`.hidden` 为隐藏） | 始终在 DOM，用 class 控制 |
| `#noticeText` | `NoticeBar.vue:21` | `.notice > span` | 内含可选 `<b>` |
| `#view-chat` | `ChatView.vue:18` | `.view`（第 0 个） | — |
| `#chatLog` | `ChatView.vue:19` | `.chat-log` | 滚动容器 |
| `#view-trace` | `TraceView.vue:25` | `.view`（第 1 个） | — |
| `#traceBody` | `TraceView.vue:39-54` | `.view:nth(1) table:nth-of-type(1) tbody` | 5 列 |
| `#msgBody` | `TraceView.vue:68-73` | `.view:nth(1) table:nth-of-type(2) tbody` | 2 列 |
| `#view-chunks` | `ChunksView.vue:35` | `.view`（第 2 个） | — |
| `#chunkSource` | `ChunksView.vue:39-42` | `.split > select` | `全部资料` + 每份资料 |
| `#chunkQuery` | `ChunksView.vue:43-48` | `.split > input` | 占位 `关键词，如：续借` |
| `#btnChunkSearch` | `ChunksView.vue:49` | `.split > .btn` | 文案 `搜索` |
| `#chunkCount` | `ChunksView.vue:50` | `.split > .hint` | `4 条 · 180/30` |
| `#chunkBody` | `ChunksView.vue:65-78` | `.view:nth(2) tbody` | 4 列 |
| `#view-batch` | `BatchView.vue:68` | `.view`（第 3 个） | — |
| `#btnBatchRun` | `BatchView.vue:70-72` | `.split > .btn.primary` | `运行对照测试` / `正在运行…` |
| `#btnBatchExport` | `BatchView.vue:73` | `.split > .btn`（第 2 个） | `导出 CSV` |
| `#batchStats` | `BatchView.vue:74` | `.split > .badge` | `查资料 10/10 · 不查资料 1/10` |
| `#batchHint` | `BatchView.vue:76` | `.view:nth(3) .hint`（第 1 个） | 人工核对提示（固定文案） |
| `#batchBar` | `BatchView.vue:77` | `.view:nth(3) .progress > i` | — |
| `#batchBody` | `BatchView.vue:95-103` | `.view:nth(3) tbody` | 7 列 |
| `#composer` | `Composer.vue:47` | `.composer` | 仅 chat 可见 |
| `#examples` | `Composer.vue:49-57` | `.examples` | 每个 `.chip[data-q]` |
| `#question` | `Composer.vue:59-67` | `textarea.question` | — |
| `#btnSend` | `Composer.vue:68-70` | `.input-row > .btn.primary` | `发送` / `正在回答…` |
| `#toast` | `ToastHost.vue` | `.toast`（`v-if toastState.visible`） | — |

**哪些 id 被保留**：只有 5 个——`#chunkSize`、`#chunkOverlap`、`#kRange`、`#modeSelect`、
`#chatKey`、`#embedKey`。理由：`<label for="...">` 需要 `id` 才能正确关联（点击 label 聚焦输入框）。
其余全部换成 class，因为 Vue 里 `ref` 取代了 `getElementById`。

**哪些 `data-*` 被保留**：`.tab[data-view]`、`.doc-item[data-name]`、`.chip[data-q]`、
`.cite[data-chunk]`。理由：它们是**测试与自动化的稳定锚点**，
比 `:nth-child()` 抗重构，也比 class 更能表达「这里装的是什么数据」。

## 四、CSS 布局关键规则（`web/src/styles/base.css`）

```css
.app {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);   /* 侧栏定宽，主区吃剩余 */
  height: 100vh;
  overflow: hidden;                               /* 让两栏各自滚动 */
}
.sidebar {
  background: var(--sidebar);
  border-right: 1px solid var(--line);
  padding: 18px 16px 28px;
  overflow-y: auto;                               /* 侧栏独立滚动 */
}
.main {
  display: flex;
  flex-direction: column;
  min-width: 0;                                   /* 关键：否则长表格撑破 grid */
  overflow: hidden;
}
.view {
  flex: 1;
  overflow-y: auto;                               /* 视图区独立滚动 */
  padding: 16px 20px 40px;
}
.view.hidden { display: none; }                   /* v-show 的实际作用 */
```

**`minmax(0, 1fr)` + `min-width: 0` 是必须的**：默认 `1fr` 的最小尺寸是 `auto`，
一旦主区里有超宽表格（检索过程 5 列、批量 7 列），`grid` 会被撑开，整页出现横向滚动条。
`minmax(0,1fr)` 允许列宽小于内容宽度，配合 `.table-wrap { overflow-x: auto }` 让表格自己横向滚。

## 五、响应式断点（只有一个）

```css
@media (max-width: 1080px) {
  .app { grid-template-columns: 1fr; grid-template-rows: auto 1fr; height: auto; min-height: 100vh; }
  .sidebar { border-right: none; border-bottom: 1px solid var(--line); max-height: 46vh; }
  .answer-grid { grid-template-columns: 1fr; }    /* both 双列改单列 */
}
```

窄屏时侧栏压到上方、占最多 46vh，主区在下。
**验收截图一律在 1600×950 或 1800×950 下拍**（示意网页是 1800×950，本次实测用 1600×950），
所以窄屏行为只在「教师用笔记本现场演示」时才生效，不影响截图。

## 六、DOM 契约的自动化验证

`web/test/app.spec.js`（3 项）就是这套契约的可执行版本：

```js
// 首屏：侧栏 + 徽章 + 示例 chip + 空态
expect(wrapper.findAll('.doc-item')).toHaveLength(6);
expect(wrapper.find('.status-line').text()).toContain('资料 6 份 · 分块 180/30');
expect(wrapper.findAll('.chip')).toHaveLength(4);

// 切 tab：只有对应视图可见，输入区仅 chat 可见
await wrapper.find('.tab[data-view="chunks"]').trigger('click');
expect(wrapper.findAll('.view').filter((v) => v.isVisible())).toHaveLength(1);
expect(wrapper.find('textarea.question').isVisible()).toBe(false);

// 发送：用户气泡 + cite + 来源卡 + honesty
await wrapper.find('textarea.question').setValue('普通图书最多同时借阅几本？借多久？');
await wrapper.find('.input-row .btn.primary').trigger('click');
expect(wrapper.find('.bubble.user').text()).toContain('普通图书');
expect(wrapper.findAll('.cite').length).toBeGreaterThan(0);
expect(wrapper.find('.honesty').text()).toContain('引用只表示取回来源');
```

**改布局时先跑这三项**，能拦住 90% 的「改样式改坏了」类回归。

## 七、交叉引用

- 组件逐个职责与交互 → `docs/04-前端设计/U03_组件与交互规格.md`
- 状态字段与数据流 → `docs/04-前端设计/U02_状态管理与数据流.md`
- 设计令牌与颜色 → `docs/04-前端设计/U04_视觉规范与设计令牌.md`
- 每个交互调哪个接口 → `docs/04-前端设计/U05_前端接口调用清单.md`
- 旧版实现（含全部 id） → `web/legacy/index.html`、`web/legacy/README.md`
