const $ = (sel) => document.querySelector(sel);
const messages = $("#messages");
const input = $("#input");
const sendBtn = $("#send");
const stageTitle = $("#stage-title");
const stageSub = $("#stage-sub");

const SAMPLES = [
  "今天终于把拖了两周的项目交了，组长点名夸了我一句",
  "明天要答辩，PPT 还有十页没做完，感觉要完蛋了",
  "又是加班到十点，真棒，这个月第六次",
  "刚把杯子放桌上了",
  "谢谢你上次陪我聊到半夜，我这两天好多了",
];

const LABEL_CN = { positive: "正向", negative: "负向", neutral: "中性" };
const STRATEGY_CN = { encourage: "鼓励", soothe: "排解", listen: "倾听", crisis: "危机兜底" };

/* ---------------- 进程状态 ---------------- */
async function probe() {
  for (const li of document.querySelectorAll("#services li")) {
    const url = li.dataset.url;
    li.classList.remove("ok", "bad");
    try {
      const r = await fetch(url, { cache: "no-store" });
      const d = await r.json();
      li.classList.add(d.ok ? "ok" : "bad");
      if (url === "/health" && d.model) {
        $("#model-line").textContent = `模型 ${d.model} · ${d.llm ? "已配置 Key" : "未配置 Key（走规则兜底）"} · pid ${d.pid}`;
      }
    } catch (e) {
      li.classList.add("bad");
    }
  }
}

async function loadMeta() {
  // 端口可以用环境变量改，所以标签从后端读，不写死
  try {
    const m = await (await fetch("/api/meta")).json();
    const set = (sel, text) => { const el = document.querySelector(sel); if (el) el.textContent = text; };
    set('#services li[data-url="/health"] .name', `后端 ${m.backend_port}`);
    set('#services li[data-url="/api/probe/sentiment"] .name', `进程1 情感识别 ${m.sentiment_port}`);
    set('#services li[data-url="/api/probe/reply"] .name', `进程2 情绪回应 ${m.reply_port}`);
  } catch (e) { /* 拿不到就保留默认文字 */ }
}

/* ---------------- DOM ---------------- */
function addMsg(role, html, cls = "") {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  wrap.innerHTML = `
    <div class="avatar">${role === "user" ? "🙂" : "🫧"}</div>
    <div class="bubble ${cls}">${html}</div>`;
  messages.appendChild(wrap);
  messages.scrollTop = messages.scrollHeight;
  return wrap.querySelector(".bubble");
}

function typingBubble() {
  const bubble = addMsg("bot", `<div class="typing"><span class="pulse"></span><span class="t">识别情绪…</span></div>`);
  return bubble;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function renderResult(bubble, data) {
  const s = data.sentiment, r = data.reply;
  const labelCls = s.label === "positive" ? "pos" : s.label === "negative" ? "neg" : "neu";
  const tips = (r.tips || []).map((t) => `<li>${esc(t)}</li>`).join("");
  const traceRows = (data.trace || [])
    .map((t) => `<div class="trace-row"><span class="stage">${esc(t.stage)}</span><span>${esc(t.node)} ${esc(t.detail || "")}</span><span class="ms">${t.ms}ms</span></div>`)
    .join("");

  bubble.innerHTML = `
    <div class="text">${esc(r.reply)}</div>
    ${r.follow_up ? `<div class="follow">↳ ${esc(r.follow_up)}</div>` : ""}
    ${tips ? `<ul class="tips">${tips}</ul>` : ""}
    <div class="meta">
      <span class="tag ${labelCls}">${LABEL_CN[s.label] || s.label} · ${esc(s.emotion)}</span>
      <span class="tag">强度 ${Number(s.intensity).toFixed(2)}</span>
      <span class="tag">置信 ${Number(s.confidence).toFixed(2)}</span>
      <span class="tag warn">${esc(STRATEGY_CN[r.strategy] || r.strategy)}</span>
      <span class="tag">${data.elapsed_ms} ms</span>
      ${data.degraded ? '<span class="tag warn">降级运行</span>' : ""}
    </div>
    ${s.reason ? `<div class="meta"><span class="tag">依据：${esc(s.reason)}</span></div>` : ""}
    <details class="trace"><summary>查看链路（${(data.trace || []).length} 步）</summary>${traceRows || "<div>无</div>"}</details>`;
  messages.scrollTop = messages.scrollHeight;
}

/* ---------------- 发送 ---------------- */
async function send(text) {
  if (!text.trim()) return;
  addMsg("user", esc(text));
  input.value = "";
  input.style.height = "auto";
  sendBtn.disabled = true;
  const bubble = typingBubble();
  const t = bubble.querySelector(".t");

  try {
    const resp = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, session_id: "web" }),
    });
    if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let final = null;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop();
      for (const part of parts) {
        const line = part.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line.slice(5).trim()); } catch { continue; }
        if (ev.type === "stage" && t) t.textContent = `${ev.stage}：${ev.detail}…`;
        if (ev.type === "final") final = ev.data;
        if (ev.type === "error" && t) t.textContent = `出错：${ev.detail}`;
      }
    }
    if (final) renderResult(bubble, final);
    else if (t) t.textContent = "没有拿到结果，看看后端日志？";
  } catch (err) {
    bubble.innerHTML = `<span style="color:#ff7a8a">请求失败：${esc(err.message)}</span>`;
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}

/* ---------------- 事件 ---------------- */
$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  send(input.value);
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send(input.value);
  }
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 140) + "px";
});

$("#btn-clear").addEventListener("click", () => {
  messages.innerHTML = "";
  stageTitle.textContent = "今天感觉怎么样？";
  stageSub.textContent = "说一句就好，不用组织语言。";
});

SAMPLES.forEach((s) => {
  const b = document.createElement("button");
  b.textContent = s.length > 16 ? s.slice(0, 16) + "…" : s;
  b.title = s;
  b.addEventListener("click", () => send(s));
  $("#chips").appendChild(b);
});

addMsg("bot", `你好，我是小暖。想聊点什么都可以——开心的事、烦心的事，或者只是随口一句。<div class="meta"><span class="tag">先由进程1 判断情绪，再由进程2 决定怎么回应</span></div>`);
loadMeta();
probe();
setInterval(probe, 5000);

// 深链接：?ask=今天好累 可以自动发一句话（方便分享具体例子 / 截图）
const preset = new URLSearchParams(location.search).get("ask");
if (preset) setTimeout(() => send(preset), 300);
