/* ==========================================================================
   多模态 RAG 前端逻辑（原生 JS，无框架无 CDN）
   职责：
     1. 上传 PDF → 轮询解析状态（待解析 / 解析中 / 解析完成 / 失败）
     2. 提问（可带图片）→ 解析 SSE → 边收边渲染
     3. 把答案里的 [S1] 角标和证据里的图片组合成「图文混排」的版面
   ========================================================================== */

'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  docs: [],
  scopeAll: true,
  selected: new Set(),
  askImages: [],          // {image_id, url, name}
  streaming: false,
  abort: null,
  health: null,
  tick: 0,
  timers: {},
};

/* ---------------------------------------------------------------- 工具 */
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function fmtBytes(n) {
  if (!n && n !== 0) return '';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0, v = Number(n);
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v < 10 && i > 0 ? v.toFixed(1) : Math.round(v)} ${u[i]}`;
}

function fmtSec(s) {
  if (s == null) return '';
  return s < 60 ? `${Number(s).toFixed(1)}s` : `${Math.floor(s / 60)}m${Math.round(s % 60)}s`;
}

function scrollThread(force) {
  const t = $('#thread');
  const near = t.scrollHeight - t.scrollTop - t.clientHeight < 220;
  if (force || near) t.scrollTop = t.scrollHeight;
}

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  const ct = r.headers.get('content-type') || '';
  const body = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) {
    const msg = (body && body.detail) || (body && body.error) || r.statusText;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return body;
}

/* ---------------------------------------------------------------- 主题 */
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem('rag-theme', theme); } catch (e) { /* 隐私模式 */ }
}

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem('rag-theme'); } catch (e) { /* ignore */ }
  const prefer = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches
    ? 'light' : 'dark';
  applyTheme(saved || prefer);
}

/* ---------------------------------------------------------------- Markdown */
const CODE_TOKEN = '\u0000C';

function inlineMd(text) {
  // 行内代码先抽出来，避免里面的 * _ 被当成强调
  const codes = [];
  let s = text.replace(/`([^`\n]+)`/g, (m, code) => {
    codes.push(code);
    return CODE_TOKEN + (codes.length - 1) + '\u0000';
  });
  s = s.replace(/\*\*\*([^*]+)\*\*\*/g, '<strong><em>$1</em></strong>');
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  s = s.replace(/~~([^~]+)~~/g, '<del>$1</del>');
  s = s.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>');
  // 引用角标 [S1] / [S1][S3]，以及「见图 S2 / 相关图片为 S8」这种裸编号
  s = s.replace(/\[\^?S(\d{1,2})\]/g,
    (m, n) => `<span class="cite" data-id="S${n}" role="button" tabindex="0">S${n}</span>`);
  s = s.replace(/(图[片表]?\s*(?:为|是|见|如下)?\s*)(S\d{1,2})/g,
    (m, prefix, n) => `${prefix}<span class="cite" data-id="${n}" role="button" tabindex="0">${n}</span>`);
  s = s.replace(/\u0000C(\d+)\u0000/g, (m, i) => `<code>${codes[Number(i)] || ''}</code>`);
  return s;
}

function mdToHtml(src) {
  const lines = String(src || '').replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let i = 0;

  const isTableRow = (ln) => /^\s*\|.*\|\s*$/.test(ln);
  const isTableSep = (ln) => /^\s*\|[\s:|-]+\|\s*$/.test(ln) && ln.includes('-');

  while (i < lines.length) {
    const line = lines[i];

    // 代码块
    const fence = line.match(/^\s*```(\w*)\s*$/);
    if (fence) {
      const buf = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) buf.push(lines[i++]);
      i++;
      out.push(`<pre><code>${esc(buf.join('\n'))}</code></pre>`);
      continue;
    }

    // 空行
    if (!line.trim()) { i++; continue; }

    // 分隔线
    if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(line)) { out.push('<hr>'); i++; continue; }

    // 标题
    const h = line.match(/^\s*(#{1,6})\s+(.*)$/);
    if (h) {
      const lv = Math.min(h[1].length, 4);
      out.push(`<h${lv}>${inlineMd(esc(h[2].trim()))}</h${lv}>`);
      i++;
      continue;
    }

    // 表格
    if (isTableRow(line) && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const head = line.trim().replace(/^\||\|$/g, '').split('|');
      i += 2;
      const rows = [];
      while (i < lines.length && isTableRow(lines[i])) {
        rows.push(lines[i].trim().replace(/^\||\|$/g, '').split('|'));
        i++;
      }
      const html = ['<table><thead><tr>']
        .concat(head.map((c) => `<th>${inlineMd(esc(c.trim()))}</th>`))
        .concat(['</tr></thead><tbody>'])
        .concat(rows.map((r) => '<tr>' + r.map((c) => `<td>${inlineMd(esc(c.trim()))}</td>`).join('') + '</tr>'))
        .concat(['</tbody></table>']);
      out.push(html.join(''));
      continue;
    }

    // 引用
    if (/^\s*>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*>\s?/, ''));
        i++;
      }
      out.push(`<blockquote>${buf.map((b) => inlineMd(esc(b))).join('<br>')}</blockquote>`);
      continue;
    }

    // 有序 / 无序列表
    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) {
        items.push(inlineMd(esc(lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, ''))));
        i++;
      }
      out.push(`<${ordered ? 'ol' : 'ul'}>${items.map((x) => `<li>${x}</li>`).join('')}</${ordered ? 'ol' : 'ul'}>`);
      continue;
    }

    // 段落
    const buf = [];
    while (i < lines.length && lines[i].trim()
      && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i])
      && !/^\s*#{1,6}\s/.test(lines[i])
      && !/^\s*```/.test(lines[i])
      && !/^\s*>\s?/.test(lines[i])
      && !isTableRow(lines[i])) {
      buf.push(lines[i]);
      i++;
    }
    out.push(`<p>${buf.map((b) => inlineMd(esc(b))).join('<br>')}</p>`);
  }
  return out.join('');
}

/* ---------------------------------------------------------------- 图片 */
function makeFigure(ev) {
  const fig = document.createElement('figure');
  fig.className = 'fig';
  const img = document.createElement('img');
  img.src = ev.image_url;
  img.alt = `${ev.filename} 第 ${ev.page || '?'} 页`;
  img.loading = 'lazy';
  img.addEventListener('click', () => openLightbox(ev.image_url));
  const cap = document.createElement('figcaption');
  const kindText = ev.kind === 'table' ? '表格' : '图片';
  cap.innerHTML = `<span class="tag">${esc(ev.id)}</span>
    <span>${esc(ev.filename)}${ev.page ? ` · 第 ${ev.page} 页` : ''} · ${kindText}</span>`;
  fig.append(img, cap);
  return fig;
}

function makeStrip(items) {
  const box = document.createElement('div');
  box.className = 'fig-strip';
  const title = document.createElement('div');
  title.className = 'strip-title';
  title.textContent = `相关图表（${items.length}）`;
  const body = document.createElement('div');
  body.className = 'strip-body';
  items.forEach((ev) => {
    const cell = document.createElement('div');
    cell.className = 'strip-item';
    const img = document.createElement('img');
    img.src = ev.image_url;
    img.loading = 'lazy';
    img.addEventListener('click', () => openLightbox(ev.image_url));
    const lab = document.createElement('span');
    lab.textContent = `${ev.id} · ${ev.filename}${ev.page ? ` p${ev.page}` : ''}`;
    lab.title = lab.textContent;
    cell.append(img, lab);
    body.append(cell);
  });
  box.append(title, body);
  return box;
}

function openLightbox(src) {
  const box = document.createElement('div');
  box.className = 'lightbox';
  const img = document.createElement('img');
  img.src = src;
  box.append(img);
  box.addEventListener('click', () => box.remove());
  const onKey = (e) => {
    if (e.key === 'Escape') { box.remove(); document.removeEventListener('keydown', onKey); }
  };
  document.addEventListener('keydown', onKey);
  document.body.append(box);
}

/* ---------------------------------------------------------------- 证据面板 */
function makeEvidence(evidence) {
  if (!evidence || !evidence.length) return null;
  const wrap = document.createElement('details');
  wrap.className = 'evidence';
  wrap.innerHTML = `<summary><span class="caret">▶</span>参考依据 ${evidence.length} 条</summary>`;
  const ul = document.createElement('ul');
  ul.className = 'ev-list';

  evidence.forEach((ev) => {
    const li = document.createElement('li');
    li.className = 'ev';
    li.dataset.id = ev.id;

    const id = document.createElement('span');
    id.className = 'ev-id';
    id.textContent = ev.id;

    const body = document.createElement('div');
    body.className = 'ev-body';
    const head = document.createElement('div');
    head.className = 'ev-head';
    const kindName = { image: '图片', table: '表格' }[ev.kind] || '正文';
    head.innerHTML = `<b>${esc(ev.filename)}</b>
      <span>${ev.page ? `第 ${ev.page} 页` : ''}</span>
      <span>${kindName}</span>
      <span>score ${Number(ev.score).toFixed(1)}</span>`;
    const text = document.createElement('div');
    text.className = 'ev-text';
    text.textContent = ev.snippet || '（仅图片）';
    body.append(head, text);
    li.append(id, body);

    if (ev.image_url) {
      const thumb = document.createElement('img');
      thumb.className = 'ev-thumb';
      thumb.src = ev.image_url;
      thumb.loading = 'lazy';
      thumb.addEventListener('click', () => openLightbox(ev.image_url));
      li.append(thumb);
    }
    ul.append(li);
  });
  wrap.append(ul);
  return wrap;
}

/* 摘要栏：把 [S1] 和证据互相点亮 */
function bindCitations(root, bubble) {
  const all = $$('.cite', root);
  all.forEach((c) => {
    const id = c.dataset.id;
    const highlight = (on) => {
      const ev = $(`.ev[data-id="${id}"]`, bubble);
      if (ev) ev.classList.toggle('on', on);
    };
    c.addEventListener('mouseenter', () => highlight(true));
    c.addEventListener('mouseleave', () => highlight(false));
    c.addEventListener('click', () => {
      const ev = $(`.ev[data-id="${id}"]`, bubble);
      const details = $('.evidence', bubble);
      if (details) details.open = true;
      if (ev) {
        ev.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        ev.classList.add('on');
        setTimeout(() => ev.classList.remove('on'), 1600);
      }
    });
    c.addEventListener('keydown', (e) => { if (e.key === 'Enter') c.click(); });
  });
}

/* 图文混排：把被引用的图片插到对应段落后，剩下的一起放进「相关图表」 */
function decorateFigures(ansEl, bubble, evidence) {
  if (!evidence || !evidence.length) return;
  const imgMap = {};
  evidence.forEach((ev) => {
    if (ev.image_url) imgMap[ev.id] = ev;
  });
  if (!Object.keys(imgMap).length) return;

  const used = new Set();
  Array.from(ansEl.children).forEach((block) => {
    if (!block.querySelector) return;
    const ids = $$('.cite', block).map((c) => c.dataset.id);
    const pick = ids.find((id) => imgMap[id] && !used.has(id));
    if (!pick) return;
    used.add(pick);
    block.insertAdjacentElement('afterend', makeFigure(imgMap[pick]));
  });

  const rest = Object.keys(imgMap).filter((id) => !used.has(id));
  if (rest.length) {
    // 正文里没引用到具体图片时，统一放进「相关图表」条带；
    // 条带标题写清楚了这些图是「相关」而不是被正文引用的，不误导读者。
    const ansEl = bubble.querySelector('.ans') || bubble;
    ansEl.append(makeStrip(rest.map((id) => imgMap[id])));
  }
}

/* ---------------------------------------------------------------- 文档库 */
function statusText(s) {
  return { PENDING: '待解析', PARSING: '解析中', DONE: '解析完成', FAILED: '解析失败' }[s] || s;
}

function renderDocs() {
  const list = $('#docList');
  list.innerHTML = '';
  $('#docCount').textContent = state.docs.length;
  $('#docsEmpty').hidden = state.docs.length > 0;

  state.docs.forEach((d) => {
    const li = document.createElement('li');
    li.className = 'doc' + (state.selected.has(d.doc_id) && !state.scopeAll ? ' active' : '');

    const top = document.createElement('div');
    top.className = 'doc-top';

    const check = document.createElement('input');
    check.type = 'checkbox';
    check.className = 'doc-check';
    check.checked = state.scopeAll || state.selected.has(d.doc_id);
    check.title = '勾选后只在这篇文档里检索';
    check.addEventListener('change', () => {
      if (state.scopeAll) {
        state.scopeAll = false;
        state.selected.clear();
        state.docs.forEach((x) => { if (x.status === 'DONE') state.selected.add(x.doc_id); });
      }
      if (check.checked) state.selected.add(d.doc_id);
      else state.selected.delete(d.doc_id);
      renderDocs();
      renderScope();
    });

    const main = document.createElement('div');
    main.className = 'doc-main';

    const name = document.createElement('div');
    name.className = 'doc-name';
    name.textContent = d.filename;
    name.title = d.filename;

    const meta = document.createElement('div');
    meta.className = 'doc-meta';
    const badge = document.createElement('span');
    badge.className = `badge ${d.status}`;
    badge.innerHTML = (d.status === 'PARSING' ? '<span class="spin"></span>' : '') + statusText(d.status);
    meta.append(badge);

    const bits = [fmtBytes(d.size_bytes)];
    if (d.status === 'DONE') {
      bits.push(`${d.pages} 页`, `${d.n_chunks} 块`);
      if (d.n_images) bits.push(`${d.n_images} 图`);
    }
    if (d.attempts > 1) bits.push(`第 ${d.attempts} 次`);
    if (d.parse_seconds != null && d.status === 'DONE') name.title = `${d.filename}（解析耗时 ${fmtSec(d.parse_seconds)}）`;
    bits.forEach((b) => {
      const s = document.createElement('span');
      s.textContent = b;
      meta.append(s);
    });

    main.append(name, meta);

    if (d.status === 'PARSING') {
      const bar = document.createElement('div');
      bar.className = 'doc-bar';
      bar.innerHTML = '<i></i>';
      main.append(bar);
    }
    if (d.status === 'FAILED' && d.error) {
      const err = document.createElement('div');
      err.className = 'doc-err';
      err.textContent = d.error;
      err.title = d.error;
      main.append(err);
    }

    const actions = document.createElement('div');
    actions.className = 'doc-actions';
    if (d.status === 'DONE') {
      const b = document.createElement('button');
      b.className = 'icon-btn';
      b.title = '查看解析出的分块';
      b.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
      b.addEventListener('click', (e) => { e.stopPropagation(); showChunks(d.doc_id); });
      actions.append(b);
    }
    const del = document.createElement('button');
    del.className = 'icon-btn danger';
    del.title = '删除文档';
    del.innerHTML = '<svg viewBox="0 0 24 24"><path d="M5 7h14M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/></svg>';
    del.addEventListener('click', (e) => { e.stopPropagation(); removeDoc(d); });
    actions.append(del);

    top.append(check, main, actions);
    li.append(top);
    list.append(li);
  });
}

function renderScope() {
  const hint = $('#scopeHint');
  if (state.scopeAll) {
    hint.textContent = '全部文档';
    hint.classList.remove('on');
  } else {
    hint.textContent = `已选 ${state.selected.size} 篇`;
    hint.classList.add('on');
  }
  $('#scopeAll').checked = state.scopeAll;
}

async function loadDocs(silent) {
  try {
    const data = await api('/api/docs');
    state.docs = data.items || [];
    renderDocs();
  } catch (e) {
    if (!silent) console.warn('加载文档失败', e);
  }
}

async function uploadFiles(files) {
  const pdfs = Array.from(files).filter((f) => /\.pdf$/i.test(f.name));
  const rejected = Array.from(files).length - pdfs.length;
  if (!pdfs.length) { showToast(rejected ? '只支持 PDF 文件' : '没有选择文件', 'err'); return; }

  const fd = new FormData();
  pdfs.forEach((f) => fd.append('files', f, f.name));

  const dz = $('#dropzone');
  dz.classList.add('busy');
  try {
    const res = await api('/api/docs', { method: 'POST', body: fd });
    const ok = res.items.filter((x) => x.ok).length;
    const dup = res.items.filter((x) => x.duplicated).length;
    const bad = res.items.filter((x) => !x.ok);
    let msg = `已提交 ${ok} 个文件到解析队列`;
    if (dup) msg += `（${dup} 个内容重复，复用已有结果）`;
    if (bad.length) msg += `；${bad.length} 个失败：${bad[0].error}`;
    showToast(msg, bad.length ? 'warn' : 'ok');
    await loadDocs();
    loadHealth();
  } catch (e) {
    showToast('上传失败：' + e.message, 'err');
  } finally {
    dz.classList.remove('busy');
    $('#fileInput').value = '';
    if (rejected) showToast(`已忽略 ${rejected} 个非 PDF 文件`, 'warn');
  }
}

async function removeDoc(doc) {
  if (!confirm(`删除《${doc.filename}》？解析结果和图片会一起清掉。`)) return;
  try {
    await api('/api/docs/' + encodeURIComponent(doc.doc_id), { method: 'DELETE' });
    state.selected.delete(doc.doc_id);
    showToast('已删除', 'ok');
    await loadDocs();
    loadHealth();
  } catch (e) {
    showToast('删除失败：' + e.message, 'err');
  }
}

async function showChunks(docId) {
  const modal = $('#modal');
  const body = $('#modalBody');
  body.textContent = '加载中…';
  modal.hidden = false;
  try {
    const data = await api(`/api/docs/${encodeURIComponent(docId)}/chunks?limit=200`);
    const d = data.doc;
    body.innerHTML = '';
    const head = document.createElement('div');
    head.style.cssText = 'margin-bottom:10px;color:var(--text)';
    head.innerHTML = `<b>${esc(d.filename)}</b> · ${d.pages} 页 · ${d.n_chunks} 块 · ${d.n_images} 图`;
    body.append(head);
    (data.items || []).forEach((c) => {
      const row = document.createElement('div');
      row.style.cssText = 'padding:7px 0;border-top:1px solid var(--border-soft)';
      const kindName = { image: '图片', table: '表格' }[c.kind] || '正文';
      const meta = document.createElement('div');
      meta.style.cssText = 'font-size:11px;color:var(--text-3);margin-bottom:2px';
      meta.textContent = `#${c.idx} · ${kindName}${c.page ? ` · p${c.page}` : ''} · ${c.n_chars} 字${c.section ? ' · ' + c.section : ''}`;
      const txt = document.createElement('div');
      txt.style.cssText = 'font-size:12px;color:var(--text-2);white-space:pre-wrap';
      txt.textContent = c.text || '（仅图片）';
      row.append(meta, txt);
      if (c.image_url) {
        const img = document.createElement('img');
        img.src = c.image_url;
        img.style.cssText = 'max-width:220px;max-height:140px;border-radius:6px;margin-top:5px;background:#fff;cursor:zoom-in';
        img.addEventListener('click', () => openLightbox(c.image_url));
        row.append(img);
      }
      body.append(row);
    });
  } catch (e) {
    body.textContent = '加载失败：' + e.message;
  }
}

/* ---------------------------------------------------------------- 管道健康 */
async function loadHealth() {
  try {
    const h = await api('/api/health');
    state.health = h;
    renderPipeline(h);
  } catch (e) {
    $('#pipeDot').className = 'dot err';
    $('#pipeText').textContent = '服务不可用';
  }
}

function renderPipeline(h) {
  const dot = $('#pipeDot');
  const text = $('#pipeText');
  const lag = (h.kafka && h.kafka.lag) || [];
  const totalLag = lag.reduce((a, b) => a + b.lag, 0);
  const active = state.docs.filter((d) => d.status === 'PENDING' || d.status === 'PARSING').length;

  const problems = [];
  if (!h.kafka.ok) problems.push('Kafka');
  if (!h.es.ok) problems.push('ES');
  if (!h.mysql.ok) problems.push('MySQL');
  if (h.mineru && h.mineru.ok === false) problems.push('MinerU');
  if (h.llm && h.llm.ok === false) problems.push('vLLM');

  if (problems.length) {
    dot.className = 'dot err';
    text.textContent = `${problems.join(' / ')} 未就绪`;
  } else if (active) {
    dot.className = 'dot busy';
    text.textContent = `${active} 篇处理中…`;
  } else if (totalLag > 0) {
    dot.className = 'dot warn';
    text.textContent = `队列积压 ${totalLag}`;
  } else {
    dot.className = 'dot ok';
    text.textContent = '全部就绪';
  }

  $('#pipeTopic').textContent = (h.config && h.config.topic_parse) || '—';
  $('#pipeGroup').textContent = (h.kafka && h.kafka.consumer_group) || '—';
  $('#pipeLag').textContent = lag.length
    ? lag.map((x) => `P${x.partition}:${x.lag}`).join(' ')
    : '—';
  const m = h.mineru || {};
  $('#pipeEngine').textContent = m.ok === false
    ? '未连接'
    : `${(h.config && h.config.mineru_tier) || 'advanced'}${m.url ? ' · 常驻' : ''}`;
}

function showPipelineModal() {
  const h = state.health;
  if (!h) return;
  const lines = [];
  lines.push('== Kafka ==');
  lines.push(`bootstrap     ${h.kafka.bootstrap}`);
  lines.push(`topics        ${(h.kafka.topics || []).join(', ')}`);
  lines.push(`消费组        ${h.kafka.consumer_group}`);
  (h.kafka.lag || []).forEach((x) => {
    lines.push(`  分区 P${x.partition}  LEO=${x.leo}  committed=${x.committed}  lag=${x.lag}`);
  });
  lines.push('');
  lines.push('== Elasticsearch ==');
  lines.push(`状态          ${h.es.status || '-'}  文档数 ${h.es.docs != null ? h.es.docs : '-'}`);
  lines.push('');
  lines.push('== MySQL ==');
  lines.push(`状态          ${h.mysql.ok ? 'ok' : 'fail'}`);
  lines.push(`文档(按状态)  ${JSON.stringify(h.mysql.documents_by_status || {})}`);
  lines.push(`分块总数      ${h.mysql.chunks || 0}   总字数 ${h.mysql.chunk_chars || 0}`);
  lines.push('');
  lines.push('== MinerU ==');
  if (h.mineru.ok) {
    lines.push(`模式          ${h.mineru.url ? '常驻服务 ' + h.mineru.url : '本地进程'}`);
    if (h.mineru.detail) lines.push(`版本          ${h.mineru.detail.version || '-'}`);
  } else {
    lines.push(`异常          ${h.mineru.error || '不可用'}`);
  }
  lines.push('');
  lines.push('== vLLM ==');
  lines.push(`模型          ${(h.llm.models || []).join(', ') || h.llm.error || '-'}`);
  lines.push('');
  lines.push('== 检索参数 ==');
  const cfg = Object.entries(h.config || {});
  const w = cfg.reduce((m, [k]) => Math.max(m, k.length), 0) + 2;
  cfg.forEach(([k, v]) => lines.push(`${k.padEnd(w)}${v}`));
  $('#modalBody').textContent = lines.join('\n');
  $('#modal').hidden = false;
}

/* ---------------------------------------------------------------- 对话 */
const thread = () => $('#thread');

function clearEmpty() {
  const e = $('#empty');
  if (e) e.remove();
}

function appendUser(text, images) {
  clearEmpty();
  const wrap = document.createElement('div');
  wrap.className = 'msg user';
  const av = document.createElement('div');
  av.className = 'avatar';
  av.textContent = '你';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  const p = document.createElement('div');
  p.textContent = text;
  bubble.append(p);
  (images || []).forEach((im) => {
    const img = document.createElement('img');
    img.className = 'thumb';
    img.src = im.url;
    img.addEventListener('click', () => openLightbox(im.url));
    bubble.append(img);
  });
  wrap.append(av, bubble);
  thread().append(wrap);
  scrollThread(true);
}

function appendBot() {
  const wrap = document.createElement('div');
  wrap.className = 'msg bot';
  const av = document.createElement('div');
  av.className = 'avatar';
  av.textContent = 'AI';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  const status = document.createElement('div');
  status.className = 'loading-line';
  status.innerHTML = '<span>正在检索文档</span><span class="dots"><span></span><span></span><span></span></span>';

  const ans = document.createElement('div');
  ans.className = 'ans';
  ans.hidden = true;

  bubble.append(status, ans);
  wrap.append(av, bubble);
  thread().append(wrap);
  scrollThread(true);
  return { wrap, bubble, status, ans };
}

function appendError(handle, message) {
  handle.status.hidden = true;
  const box = document.createElement('div');
  box.className = 'err-box';
  box.textContent = message;
  handle.bubble.append(box);
}

function appendMeta(handle, parts) {
  const meta = document.createElement('div');
  meta.className = 'msg-meta';
  meta.innerHTML = parts.filter(Boolean).join('<span class="sep">·</span>');
  handle.bubble.append(meta);
}

/* 发送 */
async function send() {
  if (state.streaming) return;
  const input = $('#input');
  const question = input.value.trim();
  if (!question) return;

  const images = state.askImages.slice();
  state.askImages = [];
  renderAttach();

  input.value = '';
  autosize(input);
  appendUser(question, images);
  const handle = appendBot();

  const docIds = state.scopeAll ? [] : Array.from(state.selected);
  setStreaming(true);

  const ctrl = new AbortController();
  state.abort = ctrl;
  let answer = '';
  let evidence = [];
  let raf = null;
  let usage = null;

  const flush = () => {
    handle.status.hidden = true;
    handle.ans.hidden = false;
    handle.ans.innerHTML = mdToHtml(answer);
  };

  try {
    const resp = await fetch('/api/qa', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        image_ids: images.map((i) => i.image_id),
        doc_ids: docIds,
      }),
      signal: ctrl.signal,
    });
    if (!resp.ok || !resp.body) {
      throw new Error(`HTTP ${resp.status}`);
    }
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = '';

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const line = chunk.split('\n').find((l) => l.startsWith('data:'));
        if (!line) continue;
        let evt;
        try { evt = JSON.parse(line.slice(5).trim()); } catch (e) { continue; }

        if (evt.type === 'start') {
          handle.status.innerHTML = '<span>正在检索文档</span><span class="dots"><span></span><span></span><span></span></span>';
        } else if (evt.type === 'retrieved') {
          evidence = evt.evidence || [];
          handle.status.innerHTML = `<span>命中 ${evidence.length} 条依据，正在生成回答</span>`
            + '<span class="dots"><span></span><span></span><span></span></span>';
        } else if (evt.type === 'delta') {
          answer += evt.text;
          if (!raf) {
            raf = requestAnimationFrame(() => { raf = null; flush(); scrollThread(); });
          }
        } else if (evt.type === 'think') {
          let think = handle.bubble.querySelector('.think');
          if (!think) {
            think = document.createElement('details');
            think.className = 'think';
            think.innerHTML = '<summary>思考过程</summary><div class="think-body"></div>';
            handle.bubble.insertBefore(think, handle.ans);
          }
          think.querySelector('.think-body').textContent += evt.text;
        } else if (evt.type === 'final') {
          answer = evt.answer || answer;
          evidence = evt.evidence || evidence;
          usage = evt.usage || null;
          if (raf) { cancelAnimationFrame(raf); raf = null; }
          flush();
          finish(handle, answer, evidence, usage, evt.elapsed, null, evt.cited);
        } else if (evt.type === 'error') {
          appendError(handle, evt.message || '生成失败');
        }
      }
    }
    if (!answer) {
      handle.status.hidden = true;
      appendError(handle, '没有收到回答，可能服务未就绪。');
    }
  } catch (e) {
    if (e.name === 'AbortError') {
      handle.status.hidden = true;
      if (answer) { flush(); finish(handle, answer, evidence, usage, null, '已停止'); }
      else appendError(handle, '已停止生成');    } else {
      appendError(handle, '请求失败：' + e.message);
    }
  } finally {
    setStreaming(false);
    state.abort = null;
  }
}

function finish(handle, answer, evidence, usage, elapsed, tag, cited) {
  handle.status.hidden = true;
  handle.ans.hidden = false;

  // 证据面板先挂上，decorateFigures / bindCitations 要靠它做角标联动
  const evPanel = makeEvidence(evidence);
  if (evPanel) handle.bubble.append(evPanel);

  // 模型没按格式标引用（或只标了一两处）时，补一条「依据」快捷条，保证引用链路不断
  let citeRow = null;
  const citedIds = Array.isArray(cited) ? cited : [];
  if (evidence.length && citedIds.length < 2) {
    citeRow = document.createElement('div');
    citeRow.className = 'cite-row';
    citeRow.innerHTML = '<span class="label">本次回答依据</span>'
      + evidence.map((e) => `<span class="cite" data-id="${esc(e.id)}" role="button" tabindex="0">${esc(e.id)}</span>`).join('');
    handle.ans.insertAdjacentElement('afterend', citeRow);
  }

  decorateFigures(handle.ans, handle.bubble, evidence);
  bindCitations(handle.ans, handle.bubble);
  if (citeRow) bindCitations(citeRow, handle.bubble);

  const parts = [];
  if (tag) parts.push(esc(tag));
  if (elapsed != null) parts.push(`耗时 ${Number(elapsed).toFixed(1)}s`);
  if (evidence.length) parts.push(`${evidence.length} 条依据`);
  const imgCount = evidence.filter((e) => e.image_url).length;
  if (imgCount) parts.push(`${imgCount} 张图`);
  if (usage && usage.completion_tokens) {
    const sec = Math.max(0.001, Number(elapsed) || 1);
    parts.push(`${usage.completion_tokens} tokens · ${(usage.completion_tokens / sec).toFixed(0)} tok/s`);
  }
  if (parts.length) appendMeta(handle, parts);
  scrollThread();
}

function setStreaming(on) {
  state.streaming = on;
  const btn = $('#btnSend');
  btn.classList.toggle('stop', on);
  btn.title = on ? '停止生成' : '发送';
  $('#input').disabled = on;
  if (!on) $('#input').focus();
}

/* ---------------------------------------------------------------- 附件 */
function renderAttach() {
  const box = $('#attachPreview');
  box.innerHTML = '';
  state.askImages.forEach((im, i) => {
    const cell = document.createElement('div');
    cell.className = 'attach-item';
    const img = document.createElement('img');
    img.src = im.url;
    const del = document.createElement('button');
    del.textContent = '×';
    del.title = '移除';
    del.addEventListener('click', () => {
      state.askImages.splice(i, 1);
      renderAttach();
    });
    cell.append(img, del);
    box.append(cell);
  });
}

async function attachImages(files) {
  for (const f of Array.from(files)) {
    if (!/^image\//.test(f.type)) continue;
    const fd = new FormData();
    fd.append('file', f, f.name);
    try {
      const res = await api('/api/ask_image', { method: 'POST', body: fd });
      state.askImages.push({ image_id: res.image_id, url: res.url, name: f.name });
      renderAttach();
    } catch (e) {
      showToast('图片上传失败：' + e.message, 'err');
    }
  }
}

/* ---------------------------------------------------------------- Toast */
let toastTimer = null;
function showToast(msg, kind) {
  let el = $('#toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    el.style.cssText = [
      'position:fixed', 'left:50%', 'bottom:132px', 'transform:translateX(-50%)',
      'max-width:min(560px,90vw)', 'padding:9px 15px', 'border-radius:10px',
      'font-size:12.5px', 'z-index:90', 'box-shadow:0 8px 30px rgba(0,0,0,.35)',
      'transition:opacity .25s ease', 'opacity:0', 'pointer-events:none',
      'border:1px solid var(--border)', 'background:var(--panel)', 'color:var(--text)',
    ].join(';');
    document.body.append(el);
  }
  el.style.borderColor = kind === 'err' ? 'var(--err)'
    : kind === 'warn' ? 'var(--warn)' : 'var(--ok)';
  el.textContent = msg;
  requestAnimationFrame(() => { el.style.opacity = '1'; });
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.style.opacity = '0'; }, 3600);
}

/* ---------------------------------------------------------------- 输入框 */
function autosize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 168) + 'px';
}

/* ---------------------------------------------------------------- 侧栏 */
function toggleSidebar(open) {
  $('#sidebar').classList.toggle('open', open);
  $('#backdrop').classList.toggle('show', open);
}

/* ---------------------------------------------------------------- 初始化 */
function bindEvents() {
  // 主题
  $('#btnTheme').addEventListener('click', () => {
    applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  });

  // 上传
  const dz = $('#dropzone');
  const fi = $('#fileInput');
  dz.addEventListener('click', () => fi.click());
  fi.addEventListener('change', () => uploadFiles(fi.files));
  ['dragenter', 'dragover'].forEach((ev) => dz.addEventListener(ev, (e) => {
    e.preventDefault();
    dz.classList.add('drag');
  }));
  ['dragleave', 'drop'].forEach((ev) => dz.addEventListener(ev, (e) => {
    e.preventDefault();
    dz.classList.remove('drag');
  }));
  dz.addEventListener('drop', (e) => {
    if (e.dataTransfer && e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
  });
  // 整页拖拽也接住
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => {
    e.preventDefault();
    if (e.dataTransfer && e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
  });

  $('#btnRefresh').addEventListener('click', async () => {
    await loadDocs();
    await loadHealth();
    showToast('已刷新', 'ok');
  });

  $('#scopeAll').addEventListener('change', (e) => {
    state.scopeAll = e.target.checked;
    state.selected.clear();
    renderDocs();
    renderScope();
  });

  // 侧栏（移动端）
  $('#btnSidebar').addEventListener('click', () => toggleSidebar(true));
  $('#btnSidebarClose').addEventListener('click', () => toggleSidebar(false));
  $('#backdrop').addEventListener('click', () => toggleSidebar(false));

  // 管道弹层
  $('#pipeline').addEventListener('click', showPipelineModal);
  $('#btnModalClose').addEventListener('click', () => { $('#modal').hidden = true; });
  $('#modal').addEventListener('click', (e) => {
    if (e.target === $('#modal')) $('#modal').hidden = true;
  });

  // 示例问题
  document.addEventListener('click', (e) => {
    const s = e.target.closest('.sample');
    if (s) {
      $('#input').value = s.dataset.q;
      autosize($('#input'));
      send();
    }
  });

  // 输入
  const input = $('#input');
  input.addEventListener('input', () => autosize(input));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      send();
    }
  });

  // 发送 / 停止
  $('#btnSend').addEventListener('click', () => {
    if (state.streaming && state.abort) state.abort.abort();
    else send();
  });

  // 图问
  const imgInput = $('#imgInput');
  $('#btnAttach').addEventListener('click', () => imgInput.click());
  imgInput.addEventListener('change', () => {
    attachImages(imgInput.files);
    imgInput.value = '';
  });

  // 粘贴图片
  input.addEventListener('paste', (e) => {
    const items = Array.from(e.clipboardData ? e.clipboardData.items : []);
    const files = items.filter((i) => i.kind === 'file').map((i) => i.getAsFile()).filter(Boolean);
    if (files.length) {
      e.preventDefault();
      attachImages(files);
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      $('#modal').hidden = true;
      toggleSidebar(false);
    }
  });
}

function startPolling() {
  state.timers.poll = setInterval(async () => {
    state.tick++;
    const active = state.docs.some((d) => d.status === 'PENDING' || d.status === 'PARSING');
    if (active) await loadDocs(true);
    if (state.tick % 3 === 1 || active) await loadHealth();
  }, 2000);
}

async function boot() {
  initTheme();
  bindEvents();
  renderScope();
  autosize($('#input'));
  await loadHealth();
  await loadDocs();
  startPolling();
  $('#input').focus();
}

document.addEventListener('DOMContentLoaded', boot);
