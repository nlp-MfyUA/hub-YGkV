"use strict";

/* QueryLab 前端：原生 JS，通过 fetch POST 调用 FastAPI SSE 接口。
   网络协议：
     POST /api/chat/stream  {"message": "..."}
     event: progress       {"stage": "..."}
     event: result         {...完整 SQL 查询结果...}
     event: error          {"message": "..."}
   注意：动态文本统一通过 textContent 插入，不将查询结果作为 HTML 解析。 */

const $ = (id) => document.getElementById(id);
const messages = $("messages");
const chatArea = $("chatArea");
const messageInput = $("messageInput");
const sendBtn = $("sendBtn");
const charCount = $("charCount");
const welcome = $("welcome");
let busy = false;

function element(tag, className = "", text = undefined) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}

function scrollBottom() {
  chatArea.scrollTop = chatArea.scrollHeight;
}

function refreshInput() {
  const len = messageInput.value.length;
  charCount.textContent = `${len}/500`;
  sendBtn.disabled = busy || !messageInput.value.trim();
  messageInput.style.height = "auto";
  messageInput.style.height = `${Math.min(messageInput.scrollHeight, 140)}px`;
}

function assistantHeader() {
  const header = element("div", "assistant-head");
  header.append(element("div", "assistant-avatar", "Q"));
  const heading = element("div");
  heading.append(element("strong", "", "SQL Agent"));
  heading.append(element("small", "", " · LangGraph 工作流"));
  header.append(heading);
  return header;
}

function userMessage(text) {
  const line = element("div", "user-line");
  line.append(element("div", "user-bubble", text));
  line.append(element("div", "user-avatar", "我"));
  return line;
}

function newConversation() {
  if (busy) return;
  messages.replaceChildren();
  messages.append(welcome);
  welcome.hidden = false;
  messageInput.value = "";
  refreshInput();
  messageInput.focus();
}

function loadingView() {
  const container = element("div", "assistant-message");
  container.append(assistantHeader());

  const body = element("div", "loading-card");
  const heading = element("div", "loading-title");
  heading.append(element("span", "spinner"));
  heading.append(element("span", "", "SQL Agent 正在分析…"));
  const current = element("div", "live-step", "准备调用 LangGraph");
  const timeline = element("div", "live-timeline");
  timeline.setAttribute("aria-live", "polite");

  body.append(heading, current, timeline);
  container.append(body);

  return {
    container,
    update(stage) {
      current.textContent = stage;
      timeline.append(element("span", "", stage));
      timeline.scrollTop = timeline.scrollHeight;
      scrollBottom();
    },
  };
}

function metadata(text) {
  return element("span", "meta-chip", text);
}

function expandable(title, symbol, startOpen = false) {
  const details = element("details", "panel");
  details.open = startOpen;
  const summary = document.createElement("summary");
  const left = element("span", "detail-label");
  left.append(element("span", "detail-icon", symbol));
  left.append(element("span", "", title));
  summary.append(left, element("span", "chevron", "⌄"));
  details.append(summary);
  const body = element("div", "detail-body");
  details.append(body);
  return { details, body };
}

function renderTable(columns, rows, shownRows, truncated) {
  const box = element("div");
  const wrapper = element("div", "table-wrap");
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const headerRow = document.createElement("tr");

  for (const label of columns) {
    headerRow.append(element("th", "", label));
  }
  head.append(headerRow);

  const tbody = document.createElement("tbody");
  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const value of row) tr.append(element("td", "", value));
    tbody.append(tr);
  }
  table.append(head, tbody);
  wrapper.append(table);
  box.append(wrapper);

  const note = element("div", "table-note");
  note.textContent = `当前显示 ${rows.length} 行 · 本次 SQL 实际已取出 ${shownRows} 行` +
    (truncated ? " · 结果已限制/截断" : "");
  box.append(note);
  return box;
}

function renderAnswer(result) {
  const container = element("div", "assistant-message");
  container.append(assistantHeader());

  const card = element("div", "answer-card");
  const main = element("div", "answer-content");
  if (!result.success) main.classList.add("answer-error");

  main.append(element("div", "answer-heading",
    result.success ? "QUERY COMPLETED" : "QUERY NEEDS ATTENTION"));
  main.append(element("div", "answer-text", result.answer || "未获得回答。"));

  const meta = element("div", "result-meta");
  meta.append(metadata(result.success ? "查询完成" : "查询未完成"));
  if ((result.tables || []).length) {
    meta.append(metadata(`使用表：${result.tables.join(" / ")}`));
  }
  if (result.sql) meta.append(metadata(`SQL 修复 ${result.repair_count || 0} 次`));
  if ((result.shown_rows || 0) > 0) meta.append(metadata(`返回 ${result.shown_rows} 行`));
  main.append(meta);
  card.append(main);

  const detailsArea = element("div", "detail-area");

  if (result.sql) {
    const { details, body } = expandable("查看生成的 SQL", "</>");
    const actions = element("div", "detail-actions");
    const copy = element("button", "subtle-action", "复制 SQL");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(result.sql);
        copy.textContent = "已复制 ✓";
        setTimeout(() => { copy.textContent = "复制 SQL"; }, 1400);
      } catch {
        copy.textContent = "无法自动复制，请手动选择代码";
      }
    });
    actions.append(copy);
    const pre = element("pre", "codeblock", result.sql);
    body.append(actions, pre);
    detailsArea.append(details);
  }

  if ((result.columns || []).length && (result.rows || []).length) {
    const { details, body } = expandable("查看数据库原始结果", "▦", true);
    body.append(renderTable(result.columns, result.rows,
      result.shown_rows || 0, !!result.truncated));
    detailsArea.append(details);
  }

  if ((result.trace || []).length) {
    const { details, body } = expandable("查看 LangGraph 节点执行过程", "⤳");
    const list = element("ol", "steps");
    for (const step of result.trace) {
      const li = element("li", "", step);
      if (step.includes("失败") || step.includes("结束")) li.classList.add("failed");
      list.append(li);
    }
    body.append(list);
    detailsArea.append(details);
  }

  card.append(detailsArea);
  container.append(card);
  return container;
}

function renderError(message) {
  return renderAnswer({
    success: false,
    answer: message,
    sql: null,
    tables: [],
    trace: [],
    rows: [],
    columns: [],
    shown_rows: 0,
    repair_count: 0,
  });
}

/* 解析标准 SSE，允许 data 跨多次网络读取；每条事件以空行结束。 */
function parseEvent(block) {
  let type = "message";
  const dataLines = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) type = line.slice(6).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  return { type, payload: JSON.parse(dataLines.join("\n")) };
}

async function askAgent(question, onProgress) {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: question }),
    cache: "no-store",
  });

  if (!response.ok) {
    let reason = `HTTP ${response.status}`;
    try {
      const error = await response.json();
      if (error.detail) reason = typeof error.detail === "string" ? error.detail : JSON.stringify(error.detail);
    } catch { /* 保留 HTTP 错误文本 */ }
    throw new Error(reason);
  }

  if (!response.body) throw new Error("浏览器不支持读取流式响应，请升级浏览器。");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;
  let streamError = "";

  function processBlock(block) {
    const evt = parseEvent(block);
    if (!evt) return;
    if (evt.type === "started") onProgress(evt.payload.message);
    if (evt.type === "progress") onProgress(evt.payload.stage);
    if (evt.type === "result") result = evt.payload;
    if (evt.type === "error") streamError = evt.payload.message || "Agent 执行失败";
  }

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");
      let end;
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        processBlock(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) processBlock(buffer);
  } finally {
    reader.releaseLock();
  }

  if (streamError) throw new Error(streamError);
  if (!result) throw new Error("服务端连接中断，未收到最终查询结果。");
  return result;
}

async function sendQuestion(text) {
  if (busy) return;
  const question = text.trim();
  if (!question) return;

  busy = true;
  welcome.hidden = true;
  messageInput.value = "";
  refreshInput();
  $("newChat").disabled = true;

  const group = element("section", "message-group");
  group.append(userMessage(question));
  const loading = loadingView();
  group.append(loading.container);
  messages.append(group);
  scrollBottom();

  try {
    const result = await askAgent(question, loading.update);
    loading.container.replaceWith(renderAnswer(result));
  } catch (error) {
    loading.container.replaceWith(renderError(error?.message || "请求失败，请检查服务端。"));
  } finally {
    busy = false;
    $("newChat").disabled = false;
    refreshInput();
    messageInput.focus();
    scrollBottom();
  }
}

$("chatForm").addEventListener("submit", (event) => {
  event.preventDefault();
  sendQuestion(messageInput.value);
});

messageInput.addEventListener("input", refreshInput);
messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    sendQuestion(messageInput.value);
  }
});

$("newChat").addEventListener("click", newConversation);

document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", () => sendQuestion(button.dataset.question));
});

async function startup() {
  try {
    const response = await fetch("/api/config", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const config = await response.json();
    $("modeBadge").textContent = config.mode === "llm" ? "✨ 真实大模型" : "🧪 离线演示";
    $("connection").classList.remove("offline");
    $("connection").lastChild.textContent = " 已连接";
  } catch {
    $("modeBadge").textContent = "连接失败";
    $("connection").classList.add("offline");
    $("connection").lastChild.textContent = " 后端未连接";
  }
}

refreshInput();
startup();
