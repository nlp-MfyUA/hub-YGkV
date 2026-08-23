#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ollama / OpenAI 兼容 网页对话客户端
- 后端：标准库 http.server，通过 openai SDK 流式调用（兼容 Ollama / OpenAI / DeepSeek 等）
- 前端：内嵌 ChatGPT 风格页面，支持多轮对话 / 多会话 / 流式输出
切换在线大模型：网页「设置」里改 API 地址 / API Key / 模型即可，无需改代码、无需重启
运行：python ollama网页客户端.py  然后浏览器打开 http://127.0.0.1:8000
"""
import http.server
import socketserver
import json
import threading
import webbrowser

from openai import OpenAI

# ===== 默认配置（仅作前端默认值；可在网页设置里随时覆盖）=====
BASE_URL = "http://localhost:11434/v1"   # Ollama 的 OpenAI 兼容端点
API_KEY = "1111"                          # Ollama 无需真实 Key，填任意值
DEFAULT_MODEL = "qwen3:0.6b-fp16"
MAX_TOKENS = 4096
PORT = 8000

# 已创建的 client 缓存，避免每次请求重建
_clients = {}
def get_client(base_url, api_key):
    key = (base_url, api_key)
    if key not in _clients:
        _clients[key] = OpenAI(base_url=base_url, api_key=api_key, timeout=120.0)
    return _clients[key]

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ollama 本地对话</title>
<script>
window.BASE_URL="__BASE_URL__"; window.API_KEY="__API_KEY__"; window.DEFAULT_MODEL="__DEFAULT_MODEL__";
</script>
<style>
  :root{
    --bg:#212121; --side:#171717; --bubble:#2f2f2f; --border:#3a3a3a;
    --text:#ececec; --muted:#9a9a9a; --accent:#10a37f; --accent-h:#0e8e6e;
    --think:#3a3320; --code-bg:#0d0d0d;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{height:100%}
  body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",Roboto,sans-serif;
       background:var(--bg);color:var(--text);display:flex;overflow:hidden}
  /* 侧边栏 */
  #sidebar{width:268px;background:var(--side);display:flex;flex-direction:column;
           border-right:1px solid var(--border);flex-shrink:0}
  #sidebar .head{padding:12px}
  #new-chat{width:100%;padding:11px;border:1px solid var(--border);background:transparent;
            color:var(--text);border-radius:8px;cursor:pointer;font-size:14px;display:flex;
            align-items:center;gap:8px;justify-content:center;transition:.15s}
  #new-chat:hover{background:var(--bubble)}
  #conv-list{flex:1;overflow-y:auto;padding:8px;margin-top:8px}
  .conv-item{padding:10px 12px;border-radius:8px;cursor:pointer;font-size:13px;
             color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
             display:flex;align-items:center;justify-content:space-between;gap:6px}
  .conv-item:hover{background:var(--bubble);color:var(--text)}
  .conv-item.active{background:var(--bubble);color:var(--text)}
  .conv-item .del{opacity:0;flex-shrink:0;padding:2px 6px;border-radius:4px}
  .conv-item:hover .del{opacity:.7}
  .conv-item .del:hover{opacity:1;background:#444}
  #sidebar .foot{padding:10px 12px;border-top:1px solid var(--border);font-size:11px;color:var(--muted)}
  /* 主区 */
  #main{flex:1;display:flex;flex-direction:column;min-width:0}
  #topbar{height:50px;border-bottom:1px solid var(--border);display:flex;align-items:center;
          padding:0 16px;gap:12px;justify-content:space-between}
  #topbar .title{font-size:14px;font-weight:600}
  #topbar .model-tag{font-size:12px;color:var(--muted);background:var(--bubble);
                     padding:4px 10px;border-radius:12px}
  #settings-btn{background:transparent;border:1px solid var(--border);color:var(--muted);
                padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px}
  #settings-btn:hover{color:var(--text)}
  #messages{flex:1;overflow-y:auto;padding:24px 0;scroll-behavior:smooth}
  .msg{max-width:760px;margin:0 auto;padding:14px 24px;display:flex;gap:16px}
  .msg .avatar{width:30px;height:30px;border-radius:6px;flex-shrink:0;display:flex;
               align-items:center;justify-content:center;font-size:13px;font-weight:700}
  .msg.user .avatar{background:var(--accent);color:#fff}
  .msg.assistant .avatar{background:#5a5a8a;color:#fff}
  .msg .body{flex:1;min-width:0;line-height:1.7;font-size:15px;overflow-wrap:break-word}
  .msg.user .body{display:flex}
  .msg.user .bubble{background:var(--bubble);padding:10px 16px;border-radius:14px}
  .msg.assistant .body{padding-top:4px}
  /* markdown */
  .body p{margin:8px 0}
  .body ul,.body ol{margin:8px 0;padding-left:24px}
  .body li{margin:4px 0}
  .body h1,.body h2,.body h3{margin:14px 0 8px}
  .body a{color:#7ab7ff}
  .body code{font-family:Consolas,Monaco,monospace;background:var(--bubble);padding:2px 6px;
             border-radius:4px;font-size:13px}
  .body pre{position:relative;background:var(--code-bg);border:1px solid var(--border);
            border-radius:8px;padding:14px;overflow-x:auto;margin:10px 0}
  .body pre code{background:none;padding:0;font-size:13px;line-height:1.5}
  .copy-btn{position:absolute;top:8px;right:8px;background:#333;color:#ccc;border:1px solid #444;
            padding:3px 9px;border-radius:5px;cursor:pointer;font-size:11px;opacity:0;transition:.15s}
  .pre-wrap:hover .copy-btn{opacity:1}
  .body blockquote{border-left:3px solid var(--accent);padding-left:12px;color:var(--muted);margin:8px 0}
  /* think 折叠 */
  details.think{background:var(--think);border:1px solid #5a4a20;border-radius:8px;
                 padding:8px 12px;margin:8px 0;font-size:13px}
  details.think summary{cursor:pointer;color:#d8c98a;font-weight:600;outline:none}
  details.think .think-body{margin-top:8px;color:#c8c8a0;white-space:pre-wrap;line-height:1.6}
  /* 光标 */
  .cursor{display:inline-block;width:8px;height:15px;background:var(--accent);vertical-align:middle;
          animation:blink 1s steps(2) infinite;margin-left:2px}
  @keyframes blink{50%{opacity:0}}
  /* 输入区 */
  #input-area{border-top:1px solid var(--border);padding:16px 24px 20px}
  #input-wrap{max-width:760px;margin:0 auto;position:relative}
  #input{width:100%;background:var(--bubble);border:1px solid var(--border);border-radius:14px;
         color:var(--text);padding:13px 56px 13px 16px;font-size:15px;font-family:inherit;
         resize:none;outline:none;max-height:180px;line-height:1.5}
  #input:focus{border-color:var(--accent)}
  #send{position:absolute;right:8px;bottom:8px;width:34px;height:34px;border-radius:50%;border:none;
        background:var(--accent);color:#fff;cursor:pointer;font-size:16px;display:flex;
        align-items:center;justify-content:center;transition:.15s}
  #send:disabled{background:#555;cursor:not-allowed}
  #send.stop{background:#c44}
  #hint{text-align:center;font-size:11px;color:var(--muted);margin-top:8px}
  /* 滚动到底部按钮 */
  #scroll-btn{position:absolute;right:calc(50% - 396px);bottom:120px;width:36px;height:36px;
              border-radius:50%;background:var(--bubble);border:1px solid var(--border);color:var(--text);
              cursor:pointer;display:none;align-items:center;justify-content:center;font-size:16px;z-index:5}
  /* 设置弹窗 */
  #modal-mask{position:fixed;inset:0;background:rgba(0,0,0,.6);display:none;align-items:center;
              justify-content:center;z-index:10}
  #modal{background:var(--side);border:1px solid var(--border);border-radius:12px;padding:22px;
         width:440px;max-width:92vw}
  #modal h3{margin-bottom:16px;font-size:16px}
  #modal label{display:block;font-size:12px;color:var(--muted);margin:14px 0 6px}
  #modal select,#modal textarea,#modal input[type=range],#modal input[type=text],#modal input[type=password]{width:100%;background:var(--bubble);
         color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px;font-family:inherit;font-size:13px}
  #modal textarea{resize:vertical;min-height:60px}
  #modal .row{display:flex;gap:10px;justify-content:flex-end;margin-top:20px}
  #modal button{padding:8px 18px;border-radius:6px;cursor:pointer;border:1px solid var(--border);
                background:transparent;color:var(--text);font-size:13px}
  #modal button.primary{background:var(--accent);border:none}
  .temp-val{color:var(--accent);font-size:12px}
  /* 滚动条 */
  ::-webkit-scrollbar{width:8px;height:8px}
  ::-webkit-scrollbar-thumb{background:#444;border-radius:4px}
  ::-webkit-scrollbar-track{background:transparent}
</style>
</head>
<body>
<div id="sidebar">
  <div class="head"><button id="new-chat">＋ 新建对话</button></div>
  <div id="conv-list"></div>
  <div class="foot">本地运行 · Ollama</div>
</div>
<div id="main">
  <div id="topbar">
    <div style="display:flex;align-items:center;gap:10px">
      <span class="title">Ollama 对话</span>
      <span class="model-tag" id="model-tag">加载中…</span>
    </div>
    <button id="settings-btn">⚙ 设置</button>
  </div>
  <div style="position:relative;flex:1;display:flex;flex-direction:column;min-height:0">
    <div id="messages"></div>
    <button id="scroll-btn">↓</button>
    <div id="input-area">
      <div id="input-wrap">
        <textarea id="input" rows="1" placeholder="输入消息，Enter 发送，Shift+Enter 换行"></textarea>
        <button id="send" title="发送">➤</button>
      </div>
      <div id="hint">由本地 Ollama 驱动，内容仅在本机处理</div>
    </div>
  </div>
</div>

<!-- 设置弹窗 -->
<div id="modal-mask">
  <div id="modal">
    <h3>设置</h3>
    <label>API 地址 (Base URL)</label>
    <input type="text" id="set-baseurl" placeholder="http://localhost:11434/v1">
    <label>API Key</label>
    <input type="password" id="set-apikey" placeholder="本地 Ollama 可填任意值">
    <label>模型</label>
    <select id="set-model"></select>
    <label>系统提示词 (System Prompt)</label>
    <textarea id="set-system" placeholder="留空则不设置"></textarea>
    <label>温度 (Temperature) <span class="temp-val" id="temp-val">0.7</span></label>
    <input type="range" id="set-temp" min="0" max="1.5" step="0.1" value="0.7">
    <div class="row">
      <button id="modal-cancel">取消</button>
      <button class="primary" id="modal-save">保存</button>
    </div>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);
let state = { conversations: [], currentId: null };
let settings = { baseUrl: window.BASE_URL, apiKey: window.API_KEY, model: window.DEFAULT_MODEL, system: '', temperature: 0.7 };
let controller = null;       // 当前流式请求的 AbortController
let rawBuf = '';             // 当前助手回复的原始累积文本
let rafPending = false;
let curBubble = null;        // 当前正在流式输出的 body 元素

/* ---------- 持久化 ---------- */
function load(){
  try{
    const s = JSON.parse(localStorage.getItem('ollama_state')||'null');
    if(s){ state = s; }
    const c = JSON.parse(localStorage.getItem('ollama_settings')||'null');
    // 合并默认值，兼容旧数据缺字段
    settings = Object.assign({baseUrl:window.BASE_URL, apiKey:window.API_KEY,
      model:window.DEFAULT_MODEL, system:'', temperature:0.7}, c||{});
  }catch(e){}
  if(!state.conversations.length) newChat();
}
function save(){
  localStorage.setItem('ollama_state', JSON.stringify(state));
  localStorage.setItem('ollama_settings', JSON.stringify(settings));
}

/* ---------- 会话管理 ---------- */
function uid(){ return Date.now().toString(36)+Math.random().toString(36).slice(2,7); }
function cur(){ return state.conversations.find(c=>c.id===state.currentId); }
function newChat(){
  const c = { id: uid(), title: '新对话', messages: [] };
  state.conversations.unshift(c);
  state.currentId = c.id;
  save(); renderSidebar(); renderMessages();
  $('#input').focus();
}
function selectChat(id){ state.currentId = id; save(); renderSidebar(); renderMessages(); }
function deleteChat(id,e){
  e.stopPropagation();
  state.conversations = state.conversations.filter(c=>c.id!==id);
  if(state.currentId===id) state.currentId = state.conversations[0]?.id || null;
  if(!state.currentId) newChat(); else { save(); renderSidebar(); renderMessages(); }
  save(); renderSidebar(); renderMessages();
}

/* ---------- 渲染 ---------- */
function renderSidebar(){
  $('#conv-list').innerHTML = state.conversations.map(c=>`
    <div class="conv-item ${c.id===state.currentId?'active':''}" onclick="selectChat('${c.id}')">
      <span>${escapeHtml(c.title)}</span>
      <span class="del" onclick="deleteChat('${c.id}',event)">✕</span>
    </div>`).join('');
}
function renderMessages(){
  const c = cur(); const box = $('#messages');
  if(!c){ box.innerHTML=''; return; }
  $('#model-tag').textContent = settings.model || DEFAULT_MODEL;
  if(!c.messages.length){
    box.innerHTML = `<div style="text-align:center;color:var(--muted);margin-top:18vh;font-size:15px">
      开始一段新对话 ✨</div>`;
    return;
  }
  box.innerHTML = c.messages.map(m=>`
    <div class="msg ${m.role}">
      <div class="avatar">${m.role==='user'?'你':'AI'}</div>
      <div class="body">${m.role==='user'?`<div class="bubble">${escapeHtml(m.content)}</div>`:renderMd(m.content)}</div>
    </div>`).join('');
  addCopyButtons(box);
  scrollToBottom(true);
}
function escapeHtml(s){ return s.replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }

/* markdown 渲染（带 think 折叠） */
function renderMd(text){
  // 拆分 <think>...</think>
  const parts = text.split(/(<\/?think>)/);
  let html='', inThink=false, thinkAcc='', ansAcc='';
  for(const p of parts){
    if(p==='<think>'){ if(ansAcc){html+=md(ansAcc);ansAcc='';} inThink=true; }
    else if(p==='</think>'){ if(thinkAcc){html+=thinkHtml(thinkAcc);thinkAcc='';} inThink=false; }
    else if(inThink){ thinkAcc+=p; } else { ansAcc+=p; }
  }
  if(thinkAcc) html+=thinkHtml(thinkAcc);   // 思考未闭合（流式中）
  if(ansAcc) html+=md(ansAcc);
  return html || '<span class="cursor"></span>';
}
function md(t){
  const blocks=[];
  let s=escapeHtml(t);
  // 提取代码块占位，避免被后续规则误伤
  s=s.replace(/```(\w*)\n?([\s\S]*?)```/g,(m,lang,code)=>{
    blocks.push('<pre><code>'+code.replace(/\n$/,'')+'</code></pre>');
    return '@@B'+(blocks.length-1)+'@@';
  });
  // 行内代码
  s=s.replace(/`([^`]+)`/g,'<code>$1</code>');
  // 标题
  s=s.replace(/^### (.*)$/gm,'<h3>$1</h3>')
     .replace(/^## (.*)$/gm,'<h2>$1</h2>')
     .replace(/^# (.*)$/gm,'<h1>$1</h1>');
  // 粗体 / 斜体
  s=s.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
  s=s.replace(/(^|[^*])\*([^*]+)\*/g,'$1<em>$2</em>');
  // 链接
  s=s.replace(/\[([^\]]+)\]\(([^)]+)\)/g,'<a href="$2" target="_blank">$1</a>');
  // 引用
  s=s.replace(/^&gt; (.*)$/gm,'<blockquote>$1</blockquote>');
  // 无序列表
  s=s.replace(/^(?:    |  - )(.*)$/gm,'<li>$1</li>')
     .replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g,'<ul>$1</ul>');
  // 段落与换行（已是块级标签的不再包 <p>）
  s=s.split(/\n{2,}/).map(p=>{
    p=p.replace(/\n/g,'<br>').trim();
    if(!p) return '';
    if(/^<(h\d|ul|ol|pre|blockquote|li|details)/.test(p)) return p;
    return '<p>'+p+'</p>';
  }).join('\n');
  // 还原代码块
  s=s.replace(/@@B(\d+)@@/g,(m,i)=>blocks[+i]);
  return s;
}
function thinkHtml(t){
  return `<details class="think"><summary>💭 思考过程</summary><div class="think-body">${escapeHtml(t)}</div></details>`;
}
function addCopyButtons(box){
  box.querySelectorAll('pre').forEach(pre=>{
    if(pre.querySelector('.copy-btn')) return;
    pre.classList.add('pre-wrap');
    const btn=document.createElement('button'); btn.className='copy-btn'; btn.textContent='复制';
    btn.onclick=()=>{ navigator.clipboard.writeText(pre.innerText); btn.textContent='已复制✓';
      setTimeout(()=>btn.textContent='复制',1500); };
    pre.appendChild(btn);
  });
}

/* ---------- 流式发送 ---------- */
async function sendMessage(){
  const input=$('#input'); const text=input.value.trim();
  if(!text || controller) return;
  const c=cur();
  // 标题用首条消息
  if(c.messages.length===0) c.title=text.slice(0,22);
  c.messages.push({role:'user',content:text});
  input.value=''; autoSize();
  save(); renderSidebar(); renderMessages();

  // 占位助手消息
  c.messages.push({role:'assistant',content:''});
  renderMessages();
  const msgs=$('#messages');
  curBubble = msgs.lastElementChild.querySelector('.body');
  curBubble.innerHTML='<span class="cursor"></span>';
  rawBuf='';
  setSending(true);

  // 构造请求消息
  const reqMsgs=[];
  if(settings.system && settings.system.trim()) reqMsgs.push({role:'system',content:settings.system});
  // 只取本会话除最后空助手消息外的历史
  c.messages.slice(0,-1).forEach(m=>reqMsgs.push({role:m.role,content:m.content}));

  controller=new AbortController();
  try{
    const resp=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        base_url:settings.baseUrl, api_key:settings.apiKey,
        model:settings.model||DEFAULT_MODEL, messages:reqMsgs,
        temperature:parseFloat(settings.temperature)
      }),signal:controller.signal});
    if(!resp.ok) throw new Error('HTTP '+resp.status);
    const reader=resp.body.getReader(); const dec=new TextDecoder(); let buf='';
    while(true){
      const {done,value}=await reader.read();
      if(done) break;
      buf+=dec.decode(value,{stream:true});
      let idx;
      while((idx=buf.indexOf('\n\n'))!==-1){
        const evt=buf.slice(0,idx); buf=buf.slice(idx+2);
        if(!evt.startsWith('data: ')) continue;
        const payload=evt.slice(6);
        if(payload==='[DONE]') break;
        try{
          const o=JSON.parse(payload);
          if(o.error) throw new Error(o.error);
          if(o.content) appendChunk(o.content);
        }catch(e){}
      }
    }
  }catch(e){
    if(e.name!=='AbortError'){
      rawBuf+=(rawBuf?'\n\n':'')+'⚠️ 请求失败：'+e.message;
    }
  }finally{
    finishStream();
  }
}
function appendChunk(delta){
  rawBuf+=delta;
  if(!rafPending){
    rafPending=true;
    requestAnimationFrame(()=>{ rafPending=false;
      if(curBubble) curBubble.innerHTML=renderMd(rawBuf);
      addCopyButtons($('#messages'));
      maybeScroll();
    });
  }
}
function finishStream(){
  controller=null; setSending(false);
  const c=cur();
  if(curBubble){
    if(rawBuf) curBubble.innerHTML=renderMd(rawBuf);
    addCopyButtons($('#messages'));
  }
  // 写回消息历史
  if(c.messages.length){
    c.messages[c.messages.length-1].content=rawBuf||'(无响应)';
  }
  curBubble=null; rawBuf=''; save();
}
function stopGen(){ if(controller){ controller.abort(); } }
function setSending(on){
  const btn=$('#send');
  if(on){ btn.classList.add('stop'); btn.textContent='■'; btn.title='停止'; }
  else{ btn.classList.remove('stop'); btn.textContent='➤'; btn.title='发送'; }
}

/* ---------- 滚动 ---------- */
function scrollToBottom(force){
  const box=$('#messages');
  box.scrollTop=box.scrollHeight;
}
function maybeScroll(){
  const box=$('#messages');
  const near=box.scrollHeight-box.scrollTop-box.clientHeight<120;
  if(near) box.scrollTop=box.scrollHeight;
  $('#scroll-btn').style.display=near?'none':'flex';
}

/* ---------- 输入框 ---------- */
function autoSize(){
  const t=$('#input'); t.style.height='auto'; t.style.height=Math.min(t.scrollHeight,180)+'px';
}

/* ---------- 设置 ---------- */
async function openSettings(){
  $('#set-system').value=settings.system;
  $('#set-temp').value=settings.temperature; $('#temp-val').textContent=settings.temperature;
  const sel=$('#set-model');
  try{
    const r=await fetch('/api/models'); const d=await r.json();
    sel.innerHTML=d.models.map(m=>`<option value="${m.name}">${m.name}</option>`).join('');
    if(settings.model) sel.value=settings.model;
  }catch(e){ sel.innerHTML=`<option>${settings.model||DEFAULT_MODEL}</option>`; }
  $('#modal-mask').style.display='flex';
}

/* ---------- 事件绑定 ---------- */
function init(){
  load();
  renderSidebar(); renderMessages();
  $('#send').onclick=()=> controller?stopGen():sendMessage();
  $('#new-chat').onclick=newChat;
  $('#input').addEventListener('input',autoSize);
  $('#input').addEventListener('keydown',e=>{
    if(e.key==='Enter'&&!e.shiftKey){ e.preventDefault(); sendMessage(); }
  });
  $('#messages').addEventListener('scroll',maybeScroll);
  $('#scroll-btn').onclick=()=>{ $('#messages').scrollTop=$('#messages').scrollHeight; };
  $('#settings-btn').onclick=openSettings;
  $('#modal-cancel').onclick=()=>$('#modal-mask').style.display='none';
  $('#modal-save').onclick=()=>{
    settings.model=$('#set-model').value;
    settings.system=$('#set-system').value;
    settings.temperature=parseFloat($('#set-temp').value);
    save(); $('#modal-mask').style.display='none';
    $('#model-tag').textContent=settings.model||DEFAULT_MODEL;
  };
  $('#set-temp').addEventListener('input',e=>$('#temp-val').textContent=e.target.value);
  $('#modal-mask').addEventListener('click',e=>{ if(e.target.id==='modal-mask') $('#modal-mask').style.display='none'; });
  autoSize();
}
window.selectChat=selectChat; window.deleteChat=deleteChat;
init();
</script>
</body>
</html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass  # 静默日志

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send_chunk(self, data: bytes):
        self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
        self.wfile.flush()

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            body = HTML.replace("__DEFAULT_MODEL__", DEFAULT_MODEL).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/models":
            try:
                r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(r.content)))
                self._cors()
                self.end_headers()
                self.wfile.write(r.content)
            except Exception as e:
                self._json_err(502, f"无法连接 Ollama: {e}")
        else:
            self._json_err(404, "Not Found")

    def do_POST(self):
        if self.path != "/api/chat":
            self._json_err(404, "Not Found")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
            payload = {
                "model": data.get("model") or DEFAULT_MODEL,
                "messages": data.get("messages", []),
                "stream": True,
            }
            if data.get("options"):
                payload["options"] = data["options"]
        except Exception as e:
            self._json_err(400, f"请求格式错误: {e}")
            return

        # 流式响应头（chunked）
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self._cors()
        self.end_headers()

        try:
            with requests.post(f"{OLLAMA_URL}/api/chat", json=payload, stream=True, timeout=None) as r:
                if r.status_code != 200:
                    err = r.text[:500]
                    self._send_chunk(f"data: {json.dumps({'error': err}, ensure_ascii=False)}\n\n".encode("utf-8"))
                    self._send_chunk(b"data: [DONE]\n\n")
                else:
                    for line in r.iter_lines():
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        content = (obj.get("message") or {}).get("content", "")
                        if content:
                            self._send_chunk(f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n".encode("utf-8"))
                        if obj.get("done"):
                            self._send_chunk(b"data: [DONE]\n\n")
                            break
        except requests.exceptions.ConnectionError:
            self._send_chunk(f"data: {json.dumps({'error': '无法连接 Ollama 服务，请确认 ollama 已启动'}, ensure_ascii=False)}\n\n".encode("utf-8"))
            self._send_chunk(b"data: [DONE]\n\n")
        except (BrokenPipeError, ConnectionResetError):
            pass  # 客户端断开（如点了停止）
        finally:
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except Exception:
                pass

    def _json_err(self, code, msg):
        body = json.dumps({"error": msg}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def main():
    server = ThreadingServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print("=" * 52)
    print("  Ollama 本地对话客户端已启动")
    print(f"  访问地址: {url}")
    print(f"  Ollama : {OLLAMA_URL}")
    print(f"  默认模型: {DEFAULT_MODEL}")
    print("  按 Ctrl+C 退出")
    print("=" * 52)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
        server.shutdown()


if __name__ == "__main__":
    main()
