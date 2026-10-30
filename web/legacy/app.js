/* 星河读书会 · 个人资料助手 前端逻辑
 * 对应功能：F1 资料管理 / F2 分块建库 / F3 状态提示 / F4 提问 / F5 来源标注
 *            F6 回答模式 / F7 检索数量 / F8 检索过程 / F9 批量对照 / F10 清空 / F11 可信度
 */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const state = {
    status: null,
    docs: [],
    mode: 'rag',
    k: 3,
    lastTrace: [],
    lastMessages: [],
    batchRows: [],
    busy: false,
  };

  /* ------------------------------------------------------------ 小工具 */
  function toast(text) {
    const el = $('toast');
    el.textContent = text;
    el.classList.add('show');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => el.classList.remove('show'), 2600);
  }

  async function api(path, options = {}) {
    const init = { ...options, headers: { ...(options.headers || {}) } };
    if (init.body && !(init.body instanceof FormData)) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(init.body);
    }
    const resp = await fetch(path, init);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(data.detail || `请求失败（HTTP ${resp.status}）`);
    }
    return data;
  }

  function esc(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* 把回答里的 [n] / [D02-C001] 变成可点击徽标（F5 点击定位） */
  function linkCitations(answer, cards) {
    const byRef = new Map();
    cards.forEach((card) => {
      byRef.set(String(card.ref), card.chunk_id);
      byRef.set(card.chunk_id, card.chunk_id);
    });
    return esc(answer).replace(/\[(\d+)\]|\[(D\d{2}-C\d{3})\]/g, (whole, num, cid) => {
      const key = num || cid;
      const chunkId = byRef.get(String(key));
      if (!chunkId) return whole;              // 无效编号保持原样，界面不造假来源
      return `<span class="cite" data-chunk="${esc(chunkId)}">${whole}</span>`;
    });
  }

  /* 片段摘录里高亮问题中的关键词（2 字以上中文片段） */
  function highlight(text, question) {
    let html = esc(text);
    const tokens = (question || '')
      .replace(/[？?。，,、；;：:！!（）()\s]/g, ' ')
      .split(' ')
      .filter((t) => t.length >= 2)
      .slice(0, 6);
    tokens.forEach((token) => {
      if (token.length < 2) return;
      html = html.split(esc(token)).join(`<mark>${esc(token)}</mark>`);
    });
    return html;
  }

  /* ------------------------------------------------------------ 渲染：状态 */
  function renderStatus(status) {
    state.status = status;
    state.mode = status.session.mode;
    state.k = status.session.k;

    $('modeSelect').value = status.session.mode;
    $('kRange').value = status.session.k;
    $('kBadge').textContent = `k = ${status.session.k}`;
    $('sessionHint').textContent = `会话 ${status.session.session_id}`;

    const kb = $('kbBadge');
    if (status.ready) {
      kb.className = 'badge';
      kb.textContent = `知识库就绪 · ${status.chunks} 片段`;
    } else if (status.stale) {
      kb.className = 'badge warn';
      kb.textContent = '需要重新建库';
    } else {
      kb.className = 'badge bad';
      kb.textContent = '知识库未建库';
    }

    $('statusText').textContent =
      `资料 ${status.doc_count} 份 · 分块 ${status.chunk_size}/${status.chunk_overlap}`;

    $('providerBadge').className = status.mock ? 'badge warn' : 'badge';
    $('providerBadge').textContent = status.mock ? '离线模拟' : '真实接口';
    $('modelHint').textContent = status.mock
      ? '当前为离线模拟档：回答由本地规则生成，用于课堂演示与自检。'
      : `对话模型 ${status.config.model || '—'} · 嵌入 ${status.config.embedding_model || '—'}`;

    $('chunkSize').value = status.chunk_size;
    $('chunkOverlap').value = status.chunk_overlap;

    const notice = $('notice');
    if (status.stale && status.message) {
      notice.classList.remove('hidden');
      $('noticeText').innerHTML = `<b>资料或分块设置已改变。</b>${esc(status.message)}`;
    } else if (status.ready) {
      notice.classList.add('hidden');
    } else if (status.message) {
      notice.classList.remove('hidden');
      $('noticeText').textContent = status.message;
    } else {
      notice.classList.add('hidden');
    }

    renderDocs(status.docs || []);
    renderExamples(status.examples || []);
    renderIndexHint(status);
  }

  function renderIndexHint(status) {
    const bar = $('indexBar');
    const hint = $('indexHint');
    const build = status.build || {};
    if (build.stage === 'running') {
      const pct = build.total ? Math.round((build.done / build.total) * 100) : 0;
      bar.style.width = `${pct}%`;
      hint.textContent = `正在建库 ${build.done}/${build.total} 片段…`;
      return;
    }
    if (build.stage === 'error') {
      bar.style.width = '0%';
      hint.textContent = `建库失败：${build.error}`;
      return;
    }
    bar.style.width = status.ready ? '100%' : '0%';
    if (status.ready) {
      hint.textContent = `建库成功，文档 ${status.doc_count} 份，片段 ${status.chunks} 条。`;
    } else if (status.stale) {
      hint.textContent = status.message || '需要重新建库。';
    } else {
      hint.textContent = '尚未建库，点击“重新建库”。';
    }
  }

  function renderDocs(docs) {
    state.docs = docs;
    const box = $('docList');
    $('docCount').textContent = `${docs.length} 份资料`;
    if (!docs.length) {
      box.innerHTML = '<div class="empty">还没有资料</div>';
      return;
    }
    box.innerHTML = docs.map((doc) => `
      <div class="doc-item" data-name="${esc(doc.name)}">
        <div class="doc-main">
          <div class="doc-name" title="${esc(doc.name)}">${esc(doc.name)}</div>
          <div class="doc-meta">
            <span>${doc.chars} 字</span><span>·</span><span>${doc.chunks} 片段</span>
            ${doc.verified ? '' : '<span class="badge warn">未核实</span>'}
          </div>
        </div>
        <button class="icon-btn" data-del="${esc(doc.name)}" title="删除">✕</button>
      </div>`).join('');

    box.querySelectorAll('.doc-item').forEach((item) => {
      item.addEventListener('click', (ev) => {
        if (ev.target.dataset.del) return;
        openDoc(item.dataset.name);
      });
    });
    box.querySelectorAll('[data-del]').forEach((btn) => {
      btn.addEventListener('click', async (ev) => {
        ev.stopPropagation();
        const name = btn.dataset.del;
        if (!confirm(`删除资料「${name}」？删除后需要重新建库。`)) return;
        try {
          await api(`/api/docs/${encodeURIComponent(name)}`, { method: 'DELETE' });
          toast(`已删除 ${name}，请重新建库`);
          await refresh();
        } catch (err) { toast(err.message); }
      });
    });

    const sourceSelect = $('chunkSource');
    const current = sourceSelect.value;
    sourceSelect.innerHTML = '<option value="">全部资料</option>' +
      docs.map((doc) => `<option value="${esc(doc.name)}">${esc(doc.name)}</option>`).join('');
    sourceSelect.value = current;
  }

  function renderExamples(examples) {
    const box = $('examples');
    if (!examples.length) { box.innerHTML = ''; return; }
    box.innerHTML = examples.map((q) => `<button class="chip" data-q="${esc(q)}">${esc(q)}</button>`).join('');
    box.querySelectorAll('[data-q]').forEach((chip) => {
      chip.addEventListener('click', () => {
        $('question').value = chip.dataset.q;
        $('question').focus();
      });
    });
  }

  async function openDoc(name) {
    try {
      const data = await api(`/api/docs/${encodeURIComponent(name)}/content`);
      const turn = document.createElement('div');
      turn.className = 'turn';
      turn.innerHTML = `
        <div class="bubble assistant">
          <div class="who">资料原文 · ${esc(data.name)} · ${data.chars} 字</div>
          <pre class="mono" style="white-space:pre-wrap;margin:0">${esc(data.text)}</pre>
        </div>`;
      const log = $('chatLog');
      if (log.querySelector('.empty')) log.innerHTML = '';
      log.appendChild(turn);
      log.scrollTop = log.scrollHeight;
      switchView('chat');
    } catch (err) { toast(err.message); }
  }

  /* ------------------------------------------------------------ 对话 */
  function appendTurn(question) {
    const log = $('chatLog');
    if (log.querySelector('.empty')) log.innerHTML = '';
    const turn = document.createElement('div');
    turn.className = 'turn';
    turn.innerHTML = `
      <div class="bubble user">${esc(question)}</div>
      <div class="bubble assistant pending">正在回答…</div>`;
    log.appendChild(turn);
    log.scrollTop = log.scrollHeight;
    return turn;
  }

  function renderAnswer(turn, payload) {
    const bubble = turn.querySelector('.bubble.assistant');
    bubble.classList.remove('pending');

    if (payload.mode === 'both') {
      bubble.innerHTML = `
        <div class="answer-grid">
          <div>
            <div class="col-head">查资料 <span class="badge">已引用知识库</span></div>
            <div class="bubble assistant" style="border:none;padding:0;box-shadow:none">${linkCitations(payload.rag.answer, payload.rag.citations)}</div>
          </div>
          <div>
            <div class="col-head">不查资料 <span class="badge ghost">未引用知识库资料</span></div>
            <div class="bubble assistant" style="border:none;padding:0;box-shadow:none">${esc(payload.direct.answer)}</div>
          </div>
        </div>`;
      renderCards(turn, payload.rag.citations || []);
      state.lastTrace = payload.rag.trace || [];
      state.lastMessages = [];
    } else {
      bubble.innerHTML = linkCitations(payload.answer, payload.citations || []);
      renderCards(turn, payload.citations || []);
      state.lastTrace = payload.trace || [];
    }

    const meta = document.createElement('div');
    meta.className = 'honesty';
    const bits = [`耗时 ${payload.elapsed_ms} ms`];
    if (payload.mode !== 'both' && !payload.used_knowledge_base && payload.mode === 'rag') {
      bits.push('本轮没有取回任何片段');
    }
    if (payload.removed_citations && payload.removed_citations.length) {
      bits.push(`已剔除无效编号 ${payload.removed_citations.join('、')}`);
    }
    bits.push('引用只表示取回来源，仍需核对原文');
    meta.textContent = bits.join(' · ');
    bubble.appendChild(meta);

    bindCitationClicks(turn);
    refreshTraceView();
  }

  function renderCards(turn, cards) {
    if (!cards || !cards.length) return;
    const wrap = document.createElement('div');
    wrap.className = 'cards';
    wrap.innerHTML = cards.map((card, index) => `
      <div class="card ${card.verified ? '' : 'unverified'}" id="card-${esc(card.chunk_id)}">
        <div class="card-head">
          <span class="idx">[${index + 1}]</span>
          <span class="mono">${esc(card.chunk_id)}</span>
          <span class="src">${esc(card.source)}</span>
          ${card.verified ? '' : '<span class="badge warn">未核实</span>'}
          <span class="score-bar"><i style="width:${Math.max(4, Math.round(card.score * 100))}%"></i></span>
          <span class="num">${card.score.toFixed(4)}</span>
          <span class="mono">第 ${card.start + 1}–${card.end} 字</span>
        </div>
        <div class="card-excerpt">${highlight(card.excerpt, $('question').value)}</div>
        <details>
          <summary>查看片段原文</summary>
          <pre>${esc(card.text)}</pre>
        </details>
      </div>`).join('');
    turn.appendChild(wrap);
  }

  function bindCitationClicks(root) {
    root.querySelectorAll('.cite').forEach((el) => {
      el.addEventListener('click', () => {
        const card = root.querySelector(`#card-${CSS.escape(el.dataset.chunk)}`);
        if (!card) return;
        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        card.classList.add('flash');
        card.querySelector('details').open = true;
        setTimeout(() => card.classList.remove('flash'), 1400);
      });
    });
  }

  async function send() {
    const box = $('question');
    const question = box.value.trim();
    if (!question || state.busy) return;
    state.busy = true;
    $('btnSend').disabled = true;
    const turn = appendTurn(question);
    box.value = '';
    box.style.height = 'auto';
    try {
      const payload = await api('/api/chat', {
        method: 'POST',
        body: { question, mode: state.mode, k: state.k },
      });
      renderAnswer(turn, payload);
      if (payload.session) {
        $('sessionHint').textContent = `会话 ${payload.session.session_id}`;
      }
    } catch (err) {
      const bubble = turn.querySelector('.bubble.assistant');
      bubble.classList.remove('pending');
      bubble.innerHTML = `<span class="fail">${esc(err.message)}</span>`;
    } finally {
      state.busy = false;
      $('btnSend').disabled = false;
      $('chatLog').scrollTop = $('chatLog').scrollHeight;
      refreshStatusQuiet();
    }
  }

  /* ------------------------------------------------------------ 检索过程 */
  function refreshTraceView() {
    const body = $('traceBody');
    const trace = state.lastTrace;
    if (!trace || !trace.length) {
      body.innerHTML = '<tr><td colspan="5" class="empty">还没有检索记录</td></tr>';
      return;
    }
    const cut = trace.filter((row) => row.retrieved).length;
    body.innerHTML = trace.map((row, index) => `
      <tr class="${row.retrieved ? 'retrieved' : ''} ${index === cut - 1 ? 'cut' : ''}">
        <td class="num">${row.rank}</td>
        <td class="mono">${esc(row.chunk_id)}</td>
        <td>${esc(row.source)}${row.verified ? '' : ' <span class="badge warn">未核实</span>'}</td>
        <td class="num">${row.score.toFixed(4)}</td>
        <td class="truncate" title="${esc(row.excerpt)}">${esc(row.excerpt)}</td>
      </tr>`).join('');
  }

  async function refreshMessages() {
    try {
      const data = await api('/api/logs/last');
      const body = $('msgBody');
      if (!data || !data.messages || !data.messages.length) {
        body.innerHTML = '<tr><td colspan="2" class="empty">还没有请求</td></tr>';
        return;
      }
      body.innerHTML = data.messages.map((msg) => `
        <tr>
          <td class="mono">${esc(msg.role)}</td>
          <td style="white-space:pre-wrap">${esc(msg.content)}</td>
        </tr>`).join('');
    } catch (err) {
      $('msgBody').innerHTML = `<tr><td colspan="2" class="empty">${esc(err.message)}</td></tr>`;
    }
  }

  /* ------------------------------------------------------------ 片段浏览 */
  async function loadChunks() {
    const source = $('chunkSource').value;
    const q = $('chunkQuery').value.trim();
    const params = new URLSearchParams();
    if (source) params.set('source', source);
    if (q) params.set('q', q);
    try {
      const data = await api(`/api/chunks?${params.toString()}`);
      $('chunkCount').textContent = `${data.total} 条 · ${data.size}/${data.overlap}`;
      const body = $('chunkBody');
      if (!data.chunks.length) {
        body.innerHTML = '<tr><td colspan="4" class="empty">没有匹配的片段</td></tr>';
        return;
      }
      body.innerHTML = data.chunks.map((chunk) => `
        <tr>
          <td class="mono">${esc(chunk.chunk_id)}</td>
          <td>${esc(chunk.source)}${chunk.verified ? '' : ' <span class="badge warn">未核实</span>'}</td>
          <td class="mono">${esc(chunk.position)}</td>
          <td style="white-space:pre-wrap">${highlight(chunk.text, q)}</td>
        </tr>`).join('');
    } catch (err) { toast(err.message); }
  }

  /* ------------------------------------------------------------ 批量对照 */
  function renderBatch(stateData) {
    const rows = stateData.rows || [];
    state.batchRows = rows;
    const body = $('batchBody');
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="7" class="empty">还没有结果</td></tr>';
    } else {
      body.innerHTML = rows.map((row) => `
        <tr>
          <td class="mono">${esc(row.id)}</td>
          <td>${esc(row.type)}</td>
          <td>${esc(row.question)}</td>
          <td style="white-space:pre-wrap">${esc(row.rag_answer)}</td>
          <td class="${row.rag_pass ? 'pass' : 'fail'}">${row.rag_pass ? '通过' : '未通过'}</td>
          <td style="white-space:pre-wrap">${esc(row.direct_answer)}</td>
          <td class="${row.direct_pass ? 'pass' : 'fail'}">${row.direct_pass ? '通过' : '未通过'}</td>
        </tr>`).join('');
    }
    const stats = stateData.stats || { total: 0, direct: 0, rag: 0 };
    $('batchStats').textContent = stats.total
      ? `查资料 ${stats.rag}/${stats.total} · 不查资料 ${stats.direct}/${stats.total}`
      : '未运行';
    const bar = $('batchBar');
    if (stateData.stage === 'running') {
      bar.style.width = stateData.total ? `${Math.round((stateData.done / stateData.total) * 100)}%` : '0%';
      $('batchHint').textContent = `正在运行 ${stateData.done}/${stateData.total} · ${stateData.current || ''}`;
    } else if (stateData.stage === 'error') {
      $('batchHint').textContent = stateData.error;
    } else if (stateData.stage === 'done') {
      bar.style.width = '100%';
      $('batchHint').textContent = stateData.export_path ? `已导出：${stateData.export_path}` : '已完成';
    } else {
      bar.style.width = '0%';
      $('batchHint').textContent = '';
    }
  }

  async function pollBatch() {
    try {
      const data = await api('/api/batch/progress');
      renderBatch(data);
      if (data.stage === 'running') {
        setTimeout(pollBatch, 400);
      } else {
        $('btnBatchRun').disabled = false;
      }
    } catch (err) {
      toast(err.message);
      $('btnBatchRun').disabled = false;
    }
  }

  /* ------------------------------------------------------------ 视图切换 */
  function switchView(name) {
    document.querySelectorAll('.tab').forEach((tab) => {
      tab.classList.toggle('active', tab.dataset.view === name);
    });
    ['chat', 'trace', 'chunks', 'batch'].forEach((key) => {
      $(`view-${key}`).classList.toggle('hidden', key !== name);
    });
    $('composer').style.display = name === 'chat' ? '' : 'none';
    if (name === 'trace') refreshMessages();
    if (name === 'chunks') loadChunks();
    if (name === 'batch') pollBatchOnce();
  }

  async function pollBatchOnce() {
    try { renderBatch(await api('/api/batch/progress')); } catch (err) { /* 忽略 */ }
  }

  /* ------------------------------------------------------------ 建库 */
  async function buildIndex() {
    const size = Number($('chunkSize').value);
    const overlap = Number($('chunkOverlap').value);
    if (!(size >= 50 && size <= 1000)) return toast('片段长度须在 50 至 1000 之间');
    if (!(overlap >= 0 && overlap < size)) return toast('重叠字数须满足 0 <= 重叠 < 片段长度');
    try {
      await api('/api/config', { method: 'POST', body: { chunk_size: size, chunk_overlap: overlap } });
      $('btnIndex').disabled = true;
      $('indexHint').textContent = '正在建库…';
      await api('/api/index', { method: 'POST' });
      const timer = setInterval(async () => {
        try {
          const data = await api('/api/index/progress');
          renderIndexHint({ ...state.status, build: data, ready: state.status.ready });
          if (data.stage !== 'running') {
            clearInterval(timer);
            $('btnIndex').disabled = false;
            await refresh();
          }
        } catch (err) {
          clearInterval(timer);
          $('btnIndex').disabled = false;
          toast(err.message);
        }
      }, 300);
    } catch (err) {
      $('btnIndex').disabled = false;
      toast(err.message);
    }
  }

  /* ------------------------------------------------------------ 刷新 */
  async function refresh() {
    const status = await api('/api/status');
    renderStatus(status);
  }

  async function refreshStatusQuiet() {
    try { await refresh(); } catch (err) { /* 静默 */ }
  }

  /* ------------------------------------------------------------ 事件绑定 */
  function bind() {
    $('btnIndex').addEventListener('click', buildIndex);

    $('btnSend').addEventListener('click', send);

    $('question').addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' && !ev.shiftKey) {
        ev.preventDefault();
        send();
      }
    });

    $('question').addEventListener('input', () => {
      const box = $('question');
      box.style.height = 'auto';
      box.style.height = `${Math.min(box.scrollHeight, 160)}px`;
    });

    $('kRange').addEventListener('input', async () => {
      state.k = Number($('kRange').value);
      $('kBadge').textContent = `k = ${state.k}`;
      try {
        await api('/api/session/params', { method: 'POST', body: { k: state.k } });
      } catch (err) { toast(err.message); }
    });

    $('modeSelect').addEventListener('change', async () => {
      state.mode = $('modeSelect').value;
      try {
        const data = await api('/api/session/params', { method: 'POST', body: { mode: state.mode } });
        $('sessionHint').textContent = `会话 ${data.session_id}`;
        if (data.mode !== state.mode) state.mode = data.mode;
      } catch (err) { toast(err.message); }
    });

    $('btnNew').addEventListener('click', async () => {
      try {
        const data = await api('/api/session/new', { method: 'POST' });
        $('sessionHint').textContent = `会话 ${data.session_id}`;
        $('chatLog').innerHTML = '<div class="empty">对话已清空，历史消息不再携带。</div>';
        state.lastTrace = [];
        refreshTraceView();
        toast('已清空对话');
      } catch (err) { toast(err.message); }
    });

    $('btnKeys').addEventListener('click', async () => {
      try {
        const data = await api('/api/keys', {
          method: 'POST',
          body: { chat_key: $('chatKey').value.trim(), embed_key: $('embedKey').value.trim() },
        });
        $('chatKey').value = '';
        $('embedKey').value = '';
        toast(data.has_keys ? '密钥已加载到内存' : '未填写密钥');
      } catch (err) { toast(err.message); }
    });

    const drop = $('dropZone');
    const input = $('fileInput');
    drop.addEventListener('click', () => input.click());
    drop.addEventListener('dragover', (ev) => { ev.preventDefault(); drop.classList.add('hot'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('hot'));
    drop.addEventListener('drop', (ev) => {
      ev.preventDefault();
      drop.classList.remove('hot');
      upload(ev.dataTransfer.files);
    });
    input.addEventListener('change', () => { upload(input.files); input.value = ''; });

    async function upload(files) {
      if (!files || !files.length) return;
      const form = new FormData();
      Array.from(files).forEach((file) => form.append('files', file));
      try {
        const data = await api('/api/docs/upload', { method: 'POST', body: form });
        const msg = [`已添加 ${data.added.length} 份`];
        if (data.skipped.length) msg.push(`跳过 ${data.skipped.length} 份：${data.skipped.join('；')}`);
        toast(msg.join('，'));
        await refresh();
      } catch (err) { toast(err.message); }
    }

    document.querySelectorAll('.tab').forEach((tab) => {
      tab.addEventListener('click', () => switchView(tab.dataset.view));
    });

    $('btnChunkSearch').addEventListener('click', loadChunks);
    $('chunkQuery').addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') loadChunks();
    });
    $('chunkSource').addEventListener('change', loadChunks);

    $('btnBatchRun').addEventListener('click', async () => {
      $('btnBatchRun').disabled = true;
      try {
        await api('/api/batch/run', { method: 'POST', body: { k: state.k } });
        pollBatch();
      } catch (err) {
        $('btnBatchRun').disabled = false;
        toast(err.message);
      }
    });

    $('btnBatchExport').addEventListener('click', async () => {
      try {
        const data = await api('/api/batch/export', { method: 'POST' });
        toast(`已导出 ${data.name}`);
        $('batchHint').textContent = `已导出：${data.path}`;
      } catch (err) { toast(err.message); }
    });
  }

  /* ------------------------------------------------------------ 启动 */
  async function boot() {
    bind();
    switchView('chat');
    try {
      await refresh();
    } catch (err) {
      toast(`无法连接后端：${err.message}`);
    }
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
