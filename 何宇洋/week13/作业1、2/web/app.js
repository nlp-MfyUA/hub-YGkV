const $ = (id) => document.getElementById(id);
let history = [];
let busy = false;
let ready = false;

// 所有用户输入、模型文本和单元格均通过 textContent 渲染。
function element(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = String(text);
  if (className) el.className = className;
  return el;
}

function message(role, text, className = '') {
  $('welcome').hidden = true;
  const el = element('article', undefined, `message ${role} ${className}`);
  el.append(element('div', role === 'user' ? '你' : 'CHINOOK', 'message-label'), element('p', text));
  $('messages').append(el);
  return el;
}

function showResult(el, data) {
  const result = data.result;
  el.append(element('div', `数据表：${data.tables.join('、') || '无'}${result ? ` · ${result.rows.length} 行${result.truncated ? ' · 仅展示部分结果' : ''}` : ''}`, 'meta'));
  if (result && result.rows.length) {
    const wrap = element('div', undefined, 'table-wrap');
    wrap.tabIndex = 0;
    wrap.setAttribute('aria-label', 'SQL 查询结果，可横向滚动');
    const table = element('table');
    const head = element('thead');
    const tr = element('tr');
    for (const name of result.columns) {
      const th = element('th', name);
      th.scope = 'col';
      tr.append(th);
    }
    head.append(tr);
    const body = element('tbody');
    for (const row of result.rows) {
      const tr = element('tr');
      for (const value of row) tr.append(element('td', value === null ? 'NULL' : value));
      body.append(tr);
    }
    table.append(head, body);
    wrap.append(table);
    el.append(wrap);
  } else {
    el.append(element('p', result ? '没有匹配的数据。' : '本次未执行查询。', 'empty-result'));
  }
  if (data.sql) {
    const details = element('details');
    details.append(element('summary', '查看执行的 SQL'), element('pre', data.sql));
    el.append(details);
  }
}

function setBusy(value) {
  busy = value;
  $('send').disabled = value || !ready;
  $('clear').disabled = value;
  document.querySelectorAll('.example,.retry').forEach((el) => el.disabled = value);
  $('question').readOnly = value;
  $('send').textContent = value ? '查询中…' : '发送 ↑';
}

async function submit(question) {
  question = question.trim();
  if (!question || busy || !ready) return;
  setBusy(true);
  message('user', question);
  $('question').value = '';
  const pending = message('assistant', '正在查询数据库，请稍候…', 'loading');
  pending.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  try {
    const response = await fetch('/api/chat', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question, history: history.slice(-8)})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '问题格式无效，请缩短后重试。');
    pending.classList.remove('loading');
    pending.querySelector('p').textContent = data.answer;
    showResult(pending, data);
    history.push({role: 'user', content: question}, {
      role: 'assistant', content: `${data.answer}\nSQL：${data.sql || ''}\n结果：${JSON.stringify(data.result)}`.slice(0, 6000)
    });
    history = history.slice(-8);
  } catch (error) {
    pending.classList.remove('loading');
    pending.classList.add('error');
    pending.querySelector('p').textContent = error instanceof TypeError ? '无法连接服务，请检查服务是否运行后重试。' : error.message;
    const retry = element('button', '重试', 'retry');
    retry.type = 'button';
    retry.addEventListener('click', () => { if (!busy) { retry.disabled = true; submit(question); } });
    pending.append(retry);
  } finally {
    setBusy(false);
    $('question').focus({preventScroll: true});
  }
}

$('chat-form').addEventListener('submit', (event) => {
  event.preventDefault();
  submit($('question').value);
});
$('question').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $('chat-form').requestSubmit();
  }
});
$('clear').addEventListener('click', () => {
  if (busy) return;
  history = [];
  $('messages').replaceChildren();
  $('welcome').hidden = false;
  $('question').value = '';
  $('question').focus();
});

async function init() {
  setBusy(false);
  try {
    const response = await fetch('/api/config');
    if (!response.ok) throw new Error('连接失败');
    const config = await response.json();
    const demo = config.mode === 'demo';
    $('mode').textContent = demo ? '离线演示' : config.model;
    $('welcome-note').textContent = demo ? '演示模式支持以下三个问题，直接查询本地真实数据。' : '输入你的问题，支持根据当前对话继续追问。';
    $('context-note').textContent = demo ? '· 不调用模型' : '· 保留最近 4 轮语境';
    for (const text of config.examples) {
      const button = element('button', text, 'example');
      button.type = 'button';
      button.append(element('span', '↗'));
      button.addEventListener('click', () => submit(text));
      $('examples').append(button);
    }
    ready = demo || config.api_key_configured;
    if (!ready) {
      $('mode').textContent = '未配置密钥';
      $('connection-error').hidden = false;
      $('connection-error').textContent = '请在服务端配置 DEEPSEEK_API_KEY，并重启服务后刷新页面。';
    }
    setBusy(false);
  } catch {
    $('mode').textContent = '连接失败';
    $('connection-error').hidden = false;
    $('connection-error').textContent = '无法连接服务，请确认服务运行后刷新页面。';
  }
}
init();
