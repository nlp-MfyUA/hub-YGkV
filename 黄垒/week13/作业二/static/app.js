/* ============================================================
   Chinook ChatBI — 前端逻辑
   - POST /api/chat/stream，用 fetch + ReadableStream 解析 SSE
   - 实时渲染 LangGraph 的每个节点（选表 / 生成 / 校验 / 改写 / 执行 / 汇总）
   - 最终渲染结论、SQL、结果表格，支持复制 SQL / 下载 CSV
   ============================================================ */
(() => {
  "use strict";

  // ---------------------------------------------------------- 示例问题
  const EXAMPLES = [
    {
      label: "客户分布",
      text: "每个国家的客户数量是多少？按客户数从多到少排序，取前 5 个。",
    },
    {
      label: "高价值客户",
      text: "销售额最高的 5 位客户是谁？请给出客户姓名和总消费金额。",
    },
    {
      label: "月度销售",
      text: "2009 年每个月的总销售额是多少？",
    },
    {
      label: "曲风统计",
      text: "Rock 类型的歌曲一共有多少首？",
    },
    {
      label: "艺术家排行",
      text: "每位艺术家的专辑数量，取前 3 名。",
    },
    {
      label: "员工客户数",
      text: "每位员工负责的客户数量是多少？按客户数排序。",
    },
  ];

  // ---------------------------------------------------------- DOM
  const $ = (id) => document.getElementById(id);
  const chatEl = $("chat");
  const messagesEl = $("messages");
  const emptyEl = $("empty");
  const examplesEl = $("examples");
  const exampleGridEl = $("exampleGrid");
  const formEl = $("composer");
  const inputEl = $("input");
  const sendEl = $("send");
  const charCountEl = $("charCount");
  const statusDotEl = $("statusDot");
  const statusTextEl = $("statusText");
  const dbMetaEl = $("dbMeta");
  const themeBtnEl = $("themeBtn");
  const newChatEl = $("newChat");
  const newChatTopEl = $("newChatTop");
  const menuBtnEl = $("menuBtn");
  const scrimEl = $("scrim");

  // ---------------------------------------------------------- 状态
  let sessionId = newSessionId();
  let busy = false;
  let controller = null;
  let stickToBottom = true;

  // ---------------------------------------------------------- 工具
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function newSessionId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return "web-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  }

  function formatSeconds(value) {
    if (typeof value !== "number" || Number.isNaN(value)) return "";
    return value < 10 ? value.toFixed(2) + "s" : Math.round(value) + "s";
  }

  function truncate(text, limit) {
    const value = String(text || "").replace(/\s+/g, " ").trim();
    return value.length > limit ? value.slice(0, limit - 1) + "…" : value;
  }

  function isNumeric(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  // ---------------------------------------------------------- 滚动
  chatEl.addEventListener(
    "scroll",
    () => {
      stickToBottom =
        chatEl.scrollHeight - chatEl.scrollTop - chatEl.clientHeight < 140;
    },
    { passive: true }
  );

  function scrollToBottom(force = false) {
    if (force) stickToBottom = true;
    if (!stickToBottom) return;
    requestAnimationFrame(() => {
      chatEl.scrollTop = chatEl.scrollHeight;
    });
  }

  // ---------------------------------------------------------- 主题
  function applyStoredTheme() {
    try {
      const saved = localStorage.getItem("chatbi-theme");
      if (saved === "light" || saved === "dark") {
        document.documentElement.dataset.theme = saved;
      }
    } catch (_) {
      /* 隐私模式下 localStorage 可能不可用 */
    }
  }

  function currentTheme() {
    const explicit = document.documentElement.dataset.theme;
    if (explicit === "light" || explicit === "dark") return explicit;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  applyStoredTheme();
  themeBtnEl.addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("chatbi-theme", next);
    } catch (_) {
      /* ignore */
    }
  });

  // ---------------------------------------------------------- 侧栏（移动端）
  function openSidebar() {
    document.body.classList.add("sidebar-open");
    scrimEl.hidden = false;
  }

  function closeSidebar() {
    document.body.classList.remove("sidebar-open");
    scrimEl.hidden = true;
  }

  menuBtnEl.addEventListener("click", openSidebar);
  scrimEl.addEventListener("click", closeSidebar);
  window.addEventListener("resize", () => {
    if (window.innerWidth > 960) closeSidebar();
  });

  // ---------------------------------------------------------- 示例
  function buildExamples() {
    EXAMPLES.forEach((example) => {
      const item = el("button", "example-item", example.text);
      item.type = "button";
      item.title = example.text;
      item.addEventListener("click", () => useExample(example.text));
      examplesEl.append(item);

      const card = el("button", "example-card");
      card.type = "button";
      card.append(el("strong", "", example.label), el("span", "", example.text));
      card.addEventListener("click", () => useExample(example.text));
      exampleGridEl.append(card);
    });
  }

  function useExample(text) {
    closeSidebar();
    if (busy) {
      inputEl.value = text;
      updateComposer();
      return;
    }
    inputEl.value = text;
    updateComposer();
    formEl.requestSubmit();
  }

  // ---------------------------------------------------------- 输入框
  function resizeInput() {
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 168) + "px";
  }

  function updateComposer() {
    const length = inputEl.value.length;
    charCountEl.textContent = `${length} / 500`;
    if (!busy) sendEl.disabled = inputEl.value.trim().length === 0;
    resizeInput();
  }

  inputEl.addEventListener("input", updateComposer);
  inputEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!busy) formEl.requestSubmit();
    }
  });

  formEl.addEventListener("submit", (event) => {
    event.preventDefault();
    if (busy) {
      stopStream();
      return;
    }
    const text = inputEl.value.trim();
    if (!text) return;
    sendMessage(text);
  });

  // ---------------------------------------------------------- 服务状态
  async function checkHealth() {
    try {
      const response = await fetch("/api/health", { cache: "no-store" });
      const data = await response.json();
      if (data.ok) {
        statusDotEl.className = "status-dot ok";
        statusTextEl.textContent = `${data.db} · ${data.tables} 张表 · ${data.model}`;
        dbMetaEl.textContent = `${data.tables} 张表 · ${data.fields} 个字段`;
      } else {
        statusDotEl.className = "status-dot err";
        statusTextEl.textContent = "服务未就绪：请检查 .env 中的 LLM_API_KEY";
        dbMetaEl.textContent = "未连接";
        inputEl.placeholder = data.error || "服务未就绪";
      }
    } catch (_) {
      statusDotEl.className = "status-dot err";
      statusTextEl.textContent = "无法连接后端服务";
      dbMetaEl.textContent = "未连接";
    }
  }

  // ---------------------------------------------------------- 消息容器
  function hideEmpty() {
    emptyEl.hidden = true;
  }

  function showEmptyIfNeeded() {
    emptyEl.hidden = messagesEl.children.length > 0;
  }

  function appendUser(text) {
    hideEmpty();
    const article = el("article", "msg user");
    const bubble = el("div", "bubble", text);
    article.append(bubble);
    messagesEl.append(article);
    scrollToBottom(true);
  }

  function chevronSvg() {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("class", "chevron");
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", "M6 9l6 6 6-6");
    svg.append(path);
    return svg;
  }

  function createAssistant() {
    const article = el("article", "msg assistant");
    const avatar = el("div", "avatar", "AI");
    const bubble = el("div", "bubble");

    const process = el("details", "process");
    process.open = true;

    const summary = el("summary");
    const spinner = el("span", "process-spinner");
    const title = el("span", "process-title", "执行过程");
    const meta = el("span", "process-meta", "正在运行…");
    summary.append(spinner, title, meta, chevronSvg());

    const stages = el("ol", "stages");
    const pending = createPendingStage("连接 SQL Agent…");
    stages.append(pending);

    process.append(summary, stages);
    bubble.append(process);
    article.append(avatar, bubble);
    messagesEl.append(article);

    return {
      article,
      bubble,
      process,
      stages,
      pending,
      meta,
      stageCount: 0,
      started: performance.now(),
      finalized: false,
    };
  }

  function createPendingStage(label) {
    const li = el("li", "stage pending");
    li.append(
      el("span", "stage-icon"),
      (() => {
        const main = el("div", "stage-main");
        main.append(el("span", "stage-name", label));
        return main;
      })(),
      el("span", "stage-time", "")
    );
    return li;
  }

  function setPendingLabel(ui, label) {
    const name = ui.pending.querySelector(".stage-name");
    if (name) name.textContent = label;
  }

  // ---------------------------------------------------------- SSE
  async function readSSE(body, onEvent) {
    const reader = body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const chunk = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        for (const line of chunk.split("\n")) {
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          try {
            onEvent(JSON.parse(payload));
          } catch (err) {
            console.error("无法解析 SSE 消息", payload, err);
          }
        }
        boundary = buffer.indexOf("\n\n");
      }
    }

    // 兼容最后一个事件没有以空行结尾的服务器实现
    if (buffer.trim().startsWith("data:")) {
      try {
        onEvent(JSON.parse(buffer.trim().slice(5).trim()));
      } catch (_) {
        /* ignore */
      }
    }
  }

  // ---------------------------------------------------------- 发送
  async function sendMessage(text) {
    hideEmpty();
    appendUser(text);

    inputEl.value = "";
    updateComposer();

    const ui = createAssistant();
    setBusy(true);
    scrollToBottom(true);

    const current = new AbortController();
    controller = current;

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId }),
        signal: current.signal,
      });

      if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
          const data = await response.json();
          if (data && data.detail) detail = data.detail;
        } catch (_) {
          /* ignore */
        }
        throw new Error(detail);
      }
      if (!response.body) throw new Error("当前浏览器不支持流式响应");

      await readSSE(response.body, (event) => handleEvent(ui, event));

      if (!ui.finalized) {
        finalizeError(ui, "服务端没有返回最终结果，请重试。");
      }
    } catch (err) {
      if (err && err.name === "AbortError") {
        markStopped(ui);
      } else {
        finalizeError(ui, (err && err.message) || String(err));
      }
    } finally {
      if (controller === current) controller = null;
      setBusy(false);
      scrollToBottom();
    }
  }

  function handleEvent(ui, event) {
    if (!event || !event.type) return;

    if (event.type === "start") {
      setPendingLabel(ui, "LangGraph 正在执行…");
      return;
    }

    if (event.type === "stage") {
      addStage(ui, event);
      return;
    }

    if (event.type === "final") {
      finalizeSuccess(ui, event);
      return;
    }

    if (event.type === "error") {
      finalizeError(ui, event.message || "执行失败");
    }
  }

  function stageState(event) {
    if (event.node === "fail") return "fail";
    if (event.node === "validate_sql") return event.sql_ok ? "ok" : "warn";
    if (event.node === "execute_sql") {
      // 执行失败会进入改写重试，用黄色提示而不是直接判失败
      if (event.ok === false || event.error) return "warn";
      return "ok";
    }
    return "ok";
  }

  function stageDetail(event) {
    if (event.node === "generate_sql" && event.sql) {
      return { text: "已生成：" + truncate(event.sql, 90), code: true };
    }
    if (event.node === "rewrite_sql" && event.sql) {
      return {
        text: `第 ${event.attempt || "?"} 次尝试：` + truncate(event.sql, 90),
        code: true,
      };
    }
    if (event.node === "execute_sql" && event.ok === false && event.error) {
      return { text: event.error, code: false };
    }
    return { text: event.detail || "", code: false };
  }

  function addStage(ui, event) {
    const detail = stageDetail(event);
    const li = el("li", "stage " + stageState(event));

    const main = el("div", "stage-main");
    main.append(el("span", "stage-name", event.name || event.node));
    if (detail.text) {
      main.append(
        el("span", "stage-detail" + (detail.code ? " is-code" : ""), detail.text)
      );
    }

    li.append(
      el("span", "stage-icon"),
      main,
      el("span", "stage-time", formatSeconds(event.elapsed))
    );

    ui.stages.insertBefore(li, ui.pending);
    ui.stageCount += 1;

    if (event.node === "summarize" || event.node === "fail") {
      ui.pending.remove();
    } else {
      setPendingLabel(ui, "正在执行下一步…");
    }
    scrollToBottom();
  }

  // ---------------------------------------------------------- 完成 / 失败
  function finishProcess(ui, label) {
    ui.process.open = false;
    ui.process.classList.add("is-done");
    if (ui.pending && ui.pending.parentNode) ui.pending.remove();
    ui.meta.textContent = label;
  }

  function renderText(container, text) {
    const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
    const parts = String(text || "").split(pattern);
    for (const part of parts) {
      if (!part) continue;
      if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
        container.append(el("strong", "", part.slice(2, -2)));
      } else if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
        container.append(el("code", "", part.slice(1, -1)));
      } else {
        container.append(document.createTextNode(part));
      }
    }
  }

  function finalizeSuccess(ui, event) {
    if (ui.finalized) return;
    ui.finalized = true;

    const elapsed =
      typeof event.elapsed === "number"
        ? event.elapsed
        : (performance.now() - ui.started) / 1000;
    const steps = ui.stageCount;
    finishProcess(ui, `完成 · ${steps} 步 · ${formatSeconds(elapsed)}`);

    const answer = el("div", "answer");
    renderText(
      answer,
      event.answer || (event.ok ? "（没有返回结论）" : "查询失败。")
    );
    ui.bubble.append(answer);

    if (!event.ok) {
      ui.bubble.append(
        errorBox(event.error || event.answer || "查询失败，请换一种问法。")
      );
      scrollToBottom();
      return;
    }

    const sql = event.sql || "";
    const columns = Array.isArray(event.columns) ? event.columns : [];
    const rows = Array.isArray(event.rows) ? event.rows : [];

    const bar = el("div", "result-bar");
    const rowChip = el("span", "chip");
    rowChip.append(el("strong", "", String(rows.length)), document.createTextNode(" 行"));
    bar.append(rowChip);

    const timeChip = el("span", "chip");
    timeChip.append(
      el("strong", "", formatSeconds(elapsed).replace("s", "")),
      document.createTextNode(" 秒")
    );
    bar.append(timeChip);

    if (Array.isArray(event.tables) && event.tables.length) {
      const tableChip = el("span", "chip", `${event.tables.length} 张表`);
      tableChip.title = event.tables.join(", ");
      bar.append(tableChip);
    }

    if (event.truncated) {
      bar.append(el("span", "chip", "结果已截断"));
    }

    let sqlBlock = null;
    if (sql) {
      const toggle = el("button", "chip accent", "查看 SQL");
      toggle.type = "button";
      toggle.setAttribute("aria-expanded", "false");
      sqlBlock = buildSqlBlock(sql);
      sqlBlock.hidden = true;
      toggle.addEventListener("click", () => {
        sqlBlock.hidden = !sqlBlock.hidden;
        toggle.setAttribute("aria-expanded", String(!sqlBlock.hidden));
        toggle.textContent = sqlBlock.hidden ? "查看 SQL" : "收起 SQL";
      });
      bar.append(toggle);

      const copy = el("button", "chip action", "复制 SQL");
      copy.type = "button";
      copy.addEventListener("click", async () => {
        const ok = await copyText(sql);
        copy.textContent = ok ? "已复制" : "复制失败";
        setTimeout(() => {
          copy.textContent = "复制 SQL";
        }, 1600);
      });
      bar.append(copy);
    }

    if (rows.length) {
      const csv = el("button", "chip action", "下载 CSV");
      csv.type = "button";
      csv.addEventListener("click", () => downloadCsv(columns, rows));
      bar.append(csv);
    }

    ui.bubble.append(bar);
    if (sqlBlock) ui.bubble.append(sqlBlock);

    if (rows.length) {
      ui.bubble.append(renderTable(columns, rows));
      if (event.truncated) {
        ui.bubble.append(
          el("div", "table-foot", "只展示前 100 行；完整数据请下载 CSV 或缩小查询范围。")
        );
      }
    } else {
      ui.bubble.append(
        el("div", "table-empty", "查询成功，但没有返回数据行。")
      );
    }

    scrollToBottom();
  }

  function finalizeError(ui, message) {
    if (ui.finalized) return;
    ui.finalized = true;
    finishProcess(ui, "执行失败");
    const answer = el("div", "answer", "这次查询没有完成。");
    ui.bubble.append(answer, errorBox(message));
    scrollToBottom();
  }

  function markStopped(ui) {
    if (ui.finalized) return;
    ui.finalized = true;
    finishProcess(ui, "已停止");
    ui.bubble.append(el("div", "stopped-note", "已停止生成。"));
  }

  function errorBox(message) {
    const box = el("div", "error-box");
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    const circle = document.createElementNS(ns, "circle");
    circle.setAttribute("cx", "12");
    circle.setAttribute("cy", "12");
    circle.setAttribute("r", "9");
    const line = document.createElementNS(ns, "path");
    line.setAttribute("d", "M12 8v5M12 16.5v.5");
    svg.append(circle, line);
    const text = el("div", "", String(message || "未知错误"));
    box.append(svg, text);
    return box;
  }

  // ---------------------------------------------------------- SQL / 表格
  const KEYWORDS =
    /\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|CROSS|ON|GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|OFFSET|WITH|AS|AND|OR|NOT|IN|IS|NULL|COUNT|SUM|AVG|MIN|MAX|DISTINCT|CASE|WHEN|THEN|ELSE|END|BETWEEN|LIKE|GLOB|STRFTIME|DATE|DATETIME|CAST|DESC|ASC|UNION|ALL|EXISTS|COALESCE|ROUND|TOTAL)\b/gi;

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function buildSqlBlock(sql) {
    const block = el("div", "sql-block");
    const code = el("pre", "sql-code");
    const highlighted = escapeHtml(sql).replace(
      KEYWORDS,
      (keyword) => `<span class="kw">${keyword}</span>`
    );
    code.innerHTML = highlighted;
    block.append(code);

    const copy = el("button", "copy-sql", "复制");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      const ok = await copyText(sql);
      copy.textContent = ok ? "已复制" : "失败";
      setTimeout(() => {
        copy.textContent = "复制";
      }, 1600);
    });
    block.append(copy);
    return block;
  }

  function renderTable(columns, rows) {
    const wrap = el("div", "table-wrap");
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    columns.forEach((column) => headRow.append(el("th", "", String(column))));
    thead.append(headRow);

    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      columns.forEach((column) => {
        const value = row ? row[column] : null;
        const cell = el(
          "td",
          "",
          value === null || value === undefined ? "—" : String(value)
        );
        if (value === null || value === undefined) cell.classList.add("null");
        if (isNumeric(value)) cell.classList.add("num");
        if (value !== null && value !== undefined) {
          cell.title = String(value);
        }
        tr.append(cell);
      });
      tbody.append(tr);
    });

    table.append(thead, tbody);
    wrap.append(table);
    return wrap;
  }

  async function copyText(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (_) {
      /* fall through */
    }
    try {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.append(area);
      area.select();
      const ok = document.execCommand("copy");
      area.remove();
      return ok;
    } catch (_) {
      return false;
    }
  }

  function csvCell(value) {
    if (value === null || value === undefined) return "";
    const text = String(value);
    return /[",\n\r]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  }

  function downloadCsv(columns, rows) {
    const lines = [
      columns.map(csvCell).join(","),
      ...rows.map((row) => columns.map((column) => csvCell(row[column])).join(",")),
    ];
    const blob = new Blob(["﻿" + lines.join("\r\n")], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    link.href = url;
    link.download = `chinook-${stamp}.csv`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  // ---------------------------------------------------------- 忙碌状态 / 新对话
  function setBusy(value) {
    busy = value;
    sendEl.classList.toggle("is-stop", value);
    sendEl.setAttribute("aria-label", value ? "停止" : "发送");
    sendEl.disabled = value ? false : inputEl.value.trim().length === 0;
  }

  function stopStream() {
    if (controller) {
      controller.abort();
    }
  }

  function newChat() {
    if (controller) {
      controller.abort();
      controller = null;
    }
    sessionId = newSessionId();
    messagesEl.textContent = "";
    emptyEl.hidden = false;
    closeSidebar();
    setBusy(false);
    inputEl.value = "";
    updateComposer();
    inputEl.focus();
    scrollToBottom(true);
  }

  newChatEl.addEventListener("click", newChat);
  newChatTopEl.addEventListener("click", newChat);

  // ---------------------------------------------------------- 启动
  buildExamples();
  updateComposer();
  showEmptyIfNeeded();
  checkHealth();
})();
