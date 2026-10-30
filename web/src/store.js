import { reactive } from 'vue';import { http } from './api.js';
import { toast } from './composables/useToast.js';

/**
 * 全局状态 + 全部动作。
 * 组件只读 state、只调 actions —— 与旧版 web/legacy/app.js 的 state 对象（8 个字段）对齐，
 * 另外补了 view（视图切换）与 turns（对话气泡列表，旧版是直接操作 DOM）。
 */
export const state = reactive({
  status: null,        // /api/status 原始返回
  docs: [],            // 资料列表
  mode: 'rag',         // 会话模式
  k: 3,                // 取回片段数
  view: 'chat',        // chat | trace | chunks | batch
  lastTrace: [],       // 最近一次检索的完整排名
  lastMessages: [],    // 最近一次实际发送的消息
  batchRows: [],       // 批量对照行
  batchState: null,    // /api/batch/progress 原始返回
  busy: false,         // 正在回答，防重入
  turns: [],           // [{id, question, status:'pending'|'done'|'fail', payload, error}]
  chunks: { rows: [], total: 0, size: 0, overlap: 0, source: '', q: '' },
  flashChunkId: '',
});

let turnSeq = 0;

/** 状态徽章三态文案（F3），与旧版 renderStatus 完全一致 */
export function kbBadge(status) {
  if (!status) return { cls: 'badge', text: '知识库未就绪' };
  if (status.ready) return { cls: 'badge', text: `知识库就绪 · ${status.chunks} 片段` };
  if (status.stale) return { cls: 'badge warn', text: '需要重新建库' };
  return { cls: 'badge bad', text: '知识库未建库' };
}

/** 建库进度提示（F2），与旧版 renderIndexHint 一致 */
export function indexHint(status) {
  const build = (status && status.build) || {};
  if (build.stage === 'running') {
    const pct = build.total ? Math.round((build.done / build.total) * 100) : 0;
    return { bar: `${pct}%`, text: `正在建库 ${build.done}/${build.total} 片段…` };
  }
  if (build.stage === 'error') {
    return { bar: '0%', text: `建库失败：${build.error}` };
  }
  if (status && status.ready) {
    return { bar: '100%', text: `建库成功，文档 ${status.doc_count} 份，片段 ${status.chunks} 条。` };
  }
  if (status && status.stale) {
    return { bar: '0%', text: status.message || '需要重新建库。' };
  }
  return { bar: '0%', text: '尚未建库，点击“重新建库”。' };
}

export const actions = {
  /** 拉取 /api/status 并把会话参数回写到本地状态 */
  async refresh() {
    const status = await http.get('/api/status');
    state.status = status;
    state.docs = status.docs || [];
    state.mode = status.session.mode;
    state.k = status.session.k;
    return status;
  },

  async refreshQuiet() {
    try { await actions.refresh(); } catch (err) { /* 静默 */ }
  },

  setView(view) {
    state.view = view;
  },

  /** F7：调整 k。立即上报会话参数 */
  async setK(k) {
    state.k = Number(k);
    const data = await http.post('/api/session/params', { k: state.k });
    if (typeof data.k === 'number') state.k = data.k;
    return data;
  },

  /** F6：切换回答模式，后端会换 session_id 并清空历史 */
  async setMode(mode) {
    state.mode = mode;
    const data = await http.post('/api/session/params', { mode });
    if (data.mode) state.mode = data.mode;
    if (state.status) state.status.session = { ...state.status.session, ...data };
    return data;
  },

  /** F10：清空对话 */
  async newSession() {
    const data = await http.post('/api/session/new');
    state.turns = [];
    state.lastTrace = [];
    if (state.status) state.status.session = { ...state.status.session, ...data };
    return data;
  },

  /** 应用密钥到内存（绝不落盘） */
  async applyKeys(chatKey, embedKey) {
    const data = await http.post('/api/keys', { chat_key: chatKey, embed_key: embedKey });
    if (state.status) state.status.has_keys = data.has_keys;
    return data;
  },

  /** 上传资料（F1） */
  async upload(files) {
    const form = new FormData();
    Array.from(files || []).forEach((file) => form.append('files', file));
    const data = await http.post('/api/docs/upload', form);
    await actions.refresh();
    return data;
  },

  /** 删除资料（F1） */
  async removeDoc(name) {
    const data = await http.del(`/api/docs/${encodeURIComponent(name)}`);
    await actions.refresh();
    return data;
  },

  /** 读取资料全文（F1 点击查看） */
  async loadDocContent(name) {
    return http.get(`/api/docs/${encodeURIComponent(name)}/content`);
  },

  /** 把资料全文作为一条 assistant 气泡插进对话（与旧版 openDoc 一致） */
  async openDoc(name) {
    const data = await actions.loadDocContent(name);
    state.turns.push({
      id: ++turnSeq,
      kind: 'doc',
      name: data.name,
      chars: data.chars,
      text: data.text,
    });
    state.view = 'chat';
    return data;
  },

  /** F2/F3：改分块设置并重建索引 */
  async buildIndex(chunkSize, chunkOverlap) {
    const size = Number(chunkSize);
    const overlap = Number(chunkOverlap);
    if (!(size >= 50 && size <= 1000)) throw new Error('片段长度须在 50 至 1000 之间');
    if (!(overlap >= 0 && overlap < size)) throw new Error('重叠字数须满足 0 <= 重叠 < 片段长度');
    await http.post('/api/config', { chunk_size: size, chunk_overlap: overlap });
    await http.post('/api/index');
    return true;
  },

  /** 建库进度轮询（供 usePolling 使用，返回 true 表示继续） */
  async pollIndex() {
    const data = await http.get('/api/index/progress');
    if (state.status) state.status.build = data;
    const running = data.stage === 'running';
    if (!running) await actions.refresh();
    return running;
  },

  /** F4：提问 */
  async send(question) {
    const text = String(question || '').trim();
    if (!text || state.busy) return null;
    state.busy = true;
    /* 注意：必须用 reactive() 包一层再 push。
     * state.turns 是 reactive 数组，读取时会返回代理，但后续我们持有的是原始对象 turn；
     * 直接改 turn.status 不经过代理，不会触发视图更新，界面会永远停在「正在回答…」。 */
    const turn = reactive({
      id: ++turnSeq,
      kind: 'qa',
      question: text,
      status: 'pending',
      payload: null,
      error: '',
    });
    state.turns.push(turn);
    try {
      const payload = await http.post('/api/chat', { question: text, mode: state.mode, k: state.k });
      turn.status = 'done';
      turn.payload = payload;
      if (payload.mode === 'both') {
        state.lastTrace = (payload.rag && payload.rag.trace) || [];
        state.lastMessages = [];
      } else {
        state.lastTrace = payload.trace || [];
      }
      if (payload.session && state.status) state.status.session = payload.session;
      return payload;
    } catch (err) {
      turn.status = 'fail';
      turn.error = err.message;
      throw err;
    } finally {
      state.busy = false;
      actions.refreshQuiet();
    }
  },

  /** 点击编号 → 定位来源卡（模板里用 flashChunkId 触发高亮） */
  focusCard(chunkId) {
    state.flashChunkId = chunkId;
    setTimeout(() => { state.flashChunkId = ''; }, 1400);
  },

  /** F8 下半表：最近一次实际发送的消息 */
  async loadLastMessages() {
    const data = await http.get('/api/logs/last');
    state.lastMessages = (data && data.messages) || [];
    return state.lastMessages;
  },

  /** 拓展B：片段浏览 */
  async loadChunks(source = '', q = '') {
    const params = new URLSearchParams();
    if (source) params.set('source', source);
    if (q) params.set('q', q);
    const data = await http.get(`/api/chunks?${params.toString()}`);
    state.chunks = {
      rows: data.chunks || [],
      total: data.total || 0,
      size: data.size,
      overlap: data.overlap,
      source,
      q,
    };
    return data;
  },

  /** F9：启动批量对照 */
  async runBatch() {
    const data = await http.post('/api/batch/run', { k: state.k });
    state.batchState = data.state || null;
    return data;
  },

  /** 批量进度轮询（返回 true 表示继续） */
  async pollBatch() {
    const data = await http.get('/api/batch/progress');
    state.batchState = data;
    state.batchRows = data.rows || [];
    return data.stage === 'running';
  },

  /** F9：导出 CSV */
  async exportBatch() {
    return http.post('/api/batch/export');
  },
};

/** 统一错误提示：组件里 catch 后调它，避免每处都写 toast(err.message) */
export function fail(err) {
  toast(err && err.message ? err.message : String(err));
}
