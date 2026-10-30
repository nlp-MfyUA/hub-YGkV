(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const thread = $("#thread");
  const empty = $("#empty");
  const form = $("#composer");
  const input = $("#input");
  const sendBtn = $("#send");

  const STAGE_TITLES = {
    schema: "解析数据库结构",
    generate: "Agent A 生成 SQL",
    check: "SQL 复核",
    execute: "执行查询",
    summarize: "自然语言归纳",
  };

  let running = false;

  /* ------------------------------------------------ 工具函数 */

  const escapeHtml = (str) =>
    String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  const fmtMs = (ms) => {
    const value = Number(ms) || 0;
    return value < 1000 ? `${Math.round(value)}ms` : `${(value / 1000).toFixed(2)}s`;
  };

  const fmtNumber = (value) => new Intl.NumberFormat("zh-CN").format(Number(value) || 0);

  const fmtClock = (date = new Date()) =>
    date.toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });

  const inline = (text) =>
    text
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

  function markdownTable(rows) {
    const cellsOf = (row) =>
      row
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => cell.trim());
    const header = cellsOf(rows[0]);
    const body = rows.slice(2).map(cellsOf);

    const wrap = makeEl("div", "table-wrap");
    const tableEl = document.createElement("table");
    tableEl.className = "grid";
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const cell of header) headRow.append(makeEl("th", "", cell));
    thead.append(headRow);
    const tbody = document.createElement("tbody");
    for (const row of body) {
      const tr = document.createElement("tr");
      for (const cell of row) tr.append(makeEl("td", /^-?\d[\d,.]*$/.test(cell) ? "num" : "", cell));
      tbody.append(tr);
    }
    tableEl.append(thead, tbody);
    wrap.append(tableEl);
    return wrap.outerHTML;
  }

  function renderText(text) {
    const lines = escapeHtml(text).split("\n");
    let html = "";
    let inList = false;
    let inCode = false;
    let codeLines = [];
    const flushList = () => {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
    };
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      const trimmed = line.trim();

      if (/^```/.test(trimmed)) {
        if (inCode) {
          html += `<pre class="inline-code">${codeLines.join("\n")}</pre>`;
          codeLines = [];
          inCode = false;
        } else {
          flushList();
          inCode = true;
        }
        index += 1;
        continue;
      }
      if (inCode) {
        codeLines.push(line);
        index += 1;
        continue;
      }

      // Markdown 表格：首行含 |，次行为分隔行
      if (
        trimmed.startsWith("|") &&
        index + 1 < lines.length &&
        /^\|?[\s:\-|]+\|[\s:\-|]*$/.test(lines[index + 1].trim())
      ) {
        flushList();
        const rows = [];
        let cursor = index;
        while (cursor < lines.length && lines[cursor].trim().startsWith("|")) {
          rows.push(lines[cursor].trim());
          cursor += 1;
        }
        html += markdownTable(rows);
        index = cursor;
        continue;
      }

      const isItem = /^\s*-\s+/.test(line);
      if (isItem) {
        if (!inList) {
          html += "<ul>";
          inList = true;
        }
        html += `<li>${inline(line.replace(/^\s*-\s+/, ""))}</li>`;
      } else {
        flushList();
        html += line + "\n";
      }
      index += 1;
    }
    flushList();
    if (inCode && codeLines.length) {
      html += `<pre class="inline-code">${codeLines.join("\n")}</pre>`;
    }
    return html;
  }

  function makeEl(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function kv(pairs) {
    const wrap = makeEl("div", "kv");
    for (const [label, value] of pairs) {
      if (value === undefined || value === null || value === "") continue;
      const item = document.createElement("span");
      item.append(`${label} `);
      if (typeof value === "string" && /[._/]/.test(value)) {
        const code = makeEl("code", "", value);
        item.append(code);
      } else {
        const strong = makeEl("b", "", String(value));
        item.append(strong);
      }
      wrap.append(item);
    }
    return wrap;
  }

  function sqlBlock(sql) {
    const wrap = makeEl("div", "sql-block");
    const pre = makeEl("pre", "", sql);
    const btn = makeEl("button", "copy", "复制");
    btn.type = "button";
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(sql);
        btn.textContent = "已复制";
        setTimeout(() => (btn.textContent = "复制"), 1200);
      } catch {
        btn.textContent = "复制失败";
      }
    });
    wrap.append(pre, btn);
    return wrap;
  }

  function details(summaryText, preText) {
    const box = document.createElement("details");
    box.className = "more";
    const summary = document.createElement("summary");
    summary.textContent = summaryText;
    const pre = makeEl("pre", "", preText);
    box.append(summary, pre);
    return box;
  }

  function table(columns, rows) {
    const wrap = makeEl("div", "table-wrap");
    const tableEl = document.createElement("table");
    tableEl.className = "grid";

    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const col of columns) headRow.append(makeEl("th", "", col));
    thead.append(headRow);

    const tbody = document.createElement("tbody");
    const shown = rows.slice(0, 100);
    for (const row of shown) {
      const tr = document.createElement("tr");
      for (const cell of row) {
        const td = document.createElement("td");
        if (cell === null) {
          td.className = "null";
          td.textContent = "NULL";
        } else if (typeof cell === "number") {
          td.className = "num";
          td.textContent = String(cell);
        } else {
          td.textContent = String(cell);
        }
        tr.append(td);
      }
      tbody.append(tr);
    }

    tableEl.append(thead, tbody);
    wrap.append(tableEl);
    return wrap;
  }

  /* ------------------------------------------------ 侧栏初始化 */

  async function loadHealth() {
    try {
      const res = await fetch("/api/health");
      const data = await res.json();
      const list = $("#model-list");
      list.innerHTML = "";
      const rows = [
        ["生成", data.models.generate],
        ["复核", data.models.check],
        ["归纳", data.models.summary],
      ];
      for (const [label, name] of rows) {
        const li = document.createElement("li");
        li.append(makeEl("span", "", label));
        li.append(makeEl("code", "", name));
        list.append(li);
      }
      if (data.schema) {
        $("#dataset-meta").textContent =
          `${data.schema.table_count} 表 · ${data.schema.column_count} 字段 · ${data.schema.foreign_key_count} 外键`;
        if (data.schema.data_range) {
          $("#dataset-range").textContent = data.schema.data_range;
        }
      }
    } catch (err) {
      console.error(err);
    }
  }

  async function loadSchema() {
    try {
      const res = await fetch("/api/schema");
      const data = await res.json();
      $("#schema-count").textContent = `${data.table_count} 表`;
      const list = $("#schema-list");
      list.innerHTML = "";
      for (const item of data.tables) {
        const row = makeEl("div", "schema-item");
        row.title = item.columns.map((c) => `${c.name} ${c.type}`).join("\n");
        row.append(makeEl("code", "", item.name));
        row.append(makeEl("span", "", `${item.rows} 行`));
        list.append(row);
      }
    } catch (err) {
      console.error(err);
      $("#schema-count").textContent = "读取失败";
    }
  }

  /* ------------------------------------------------ 轮次与阶段 */

  function createTurn(question) {
    if (empty && empty.parentNode) empty.remove();
    const turn = {
      el: makeEl("article", "turn"),
      stages: new Map(),
      counter: 0,
      answerText: "",
      startedAt: performance.now(),
    };

    const q = makeEl("div", "turn-q");
    q.append(makeEl("span", "q-badge", "问"));
    q.append(makeEl("p", "", question));
    q.append(makeEl("time", "", fmtClock()));

    turn.stagesEl = makeEl("div", "stages");
    turn.answerEl = makeEl("div", "answer");
    turn.answerLabel = makeEl("div", "answer-label", "回答");
    turn.answerTextEl = makeEl("div", "answer-text");
    turn.caret = makeEl("span", "caret");
    turn.answerTextEl.append(turn.caret);
    turn.answerFootEl = makeEl("div", "answer-foot");
    turn.answerEl.append(turn.answerLabel, turn.answerTextEl, turn.answerFootEl);
    turn.answerEl.style.display = "none";

    turn.el.append(q, turn.stagesEl, turn.answerEl);
    thread.append(turn.el);
    thread.scrollTop = thread.scrollHeight;
    return turn;
  }

  function stageKey(stage, round) {
    return `${stage}:${round || 0}`;
  }

  function ensureStage(turn, stage, round, status) {
    const key = stageKey(stage, round);
    if (turn.stages.has(key)) return turn.stages.get(key);

    const tpl = $("#stage-template");
    const node = tpl.content.firstElementChild.cloneNode(true);
    turn.counter += 1;

    const label = STAGE_TITLES[stage] || stage;
    const title = $(".title", node);
    title.textContent = label;
    if (round) {
      const tag = makeEl("span", "note muted", ` 第 ${round} 轮`);
      title.append(tag);
    }
    $(".num", node).textContent = String(turn.counter).padStart(2, "0");
    $(".badge-status", node).textContent = status === "running" ? "进行中" : status === "done" ? "完成" : "失败";
    node.classList.add(`is-${status}`);

    turn.stagesEl.append(node);
    turn.stages.set(key, node);
    return node;
  }

  function setStageState(node, status, elapsed) {
    node.classList.remove("is-running", "is-done", "is-error");
    node.classList.add(`is-${status}`);
    $(".badge-status", node).textContent =
      status === "running" ? "进行中" : status === "done" ? "完成" : "失败";
    $(".dur", node).textContent = status === "running" ? "—" : fmtMs(elapsed);
  }

  function appendBody(node, ...children) {
    const body = $(".stage-body", node);
    for (const child of children) if (child) body.append(child);
  }

  /* ------------------------------------------------ 各阶段渲染 */

  function renderSchema(node, payload) {
    appendBody(
      node,
      kv([
        ["表", payload.table_count],
        ["字段", payload.column_count],
        ["外键", payload.foreign_key_count],
      ]),
      makeEl("div", "note muted", `结构来源：${payload.db_path}`)
    );
  }

  function renderGenerate(node, payload) {
    appendBody(node, kv([["模型", payload.model], ["工具调用", `${(payload.tools || []).length} 次`]]));
    if (payload.reasoning) {
      appendBody(node, makeEl("div", "note", `口径说明：${payload.reasoning}`));
    }
    if (payload.sql) {
      appendBody(node, sqlBlock(payload.sql));
    }
    if (payload.tools && payload.tools.length) {
      const wrap = makeEl("div", "tools");
      for (const tool of payload.tools) {
        const chip = makeEl("span", "tool", tool.name);
        chip.title = tool.args || "";
        wrap.append(chip);
      }
      appendBody(node, wrap);
    }
    appendBody(node, makeEl("div", "note muted", `调用 ${payload.usage?.requests || 0} 次 · ${fmtNumber(payload.usage?.total_tokens || 0)} tokens`));
  }

  function renderCheck(node, payload) {
    const approved = Boolean(payload.approved);
    const verdict = makeEl("div", `verdict ${approved ? "pass" : "fail"}`, approved ? "复核通过" : "复核未通过");
    verdict.append(makeEl("span", "", ` · 风险 ${payload.risk || "—"}`));
    appendBody(node, verdict);

    const sourceText =
      payload.source === "static"
        ? "静态校验拦截（未进入模型复核）"
        : payload.source === "llm-fallback"
          ? `主复核模型超时，已降级为 ${payload.model || "备用模型"} 复核`
          : `静态校验通过 + 模型复核（${payload.model || "—"}）`;
    appendBody(node, makeEl("div", "note muted", sourceText));

    if (payload.issues && payload.issues.length) {
      const ul = makeEl("ul", "issues");
      for (const issue of payload.issues) ul.append(makeEl("li", "", issue));
      appendBody(node, ul);
    }
    if (payload.suggestion && !payload.unrecoverable) {
      const full = String(payload.suggestion);
      if (full.length > 160) {
        appendBody(node, makeEl("div", "note", `建议：${full.slice(0, 160)}…`));
        appendBody(node, details("展开完整建议", full));
      } else {
        appendBody(node, makeEl("div", "note", `建议：${full}`));
      }
    }
    if (payload.warnings && payload.warnings.length) {
      const ul = makeEl("ul", "warns");
      for (const warning of payload.warnings) ul.append(makeEl("li", "", warning));
      appendBody(node, ul);
    }
    if (payload.plan && payload.plan.length) {
      appendBody(node, details("查看执行计划", payload.plan.join("\n")));
    }
    if (payload.usage && payload.usage.total_tokens) {
      appendBody(node, makeEl("div", "note muted", `复核消耗 ${fmtNumber(payload.usage.total_tokens)} tokens`));
    }
  }

  function renderExecute(node, payload) {
    const kvPairs = [
      ["返回行数", payload.row_count],
      ["列数", (payload.columns || []).length],
    ];
    if (payload.truncated) kvPairs.push(["截断", `仅前 ${payload.max_rows} 行`]);
    appendBody(node, kv(kvPairs));
    if (payload.columns && payload.columns.length) {
      appendBody(node, table(payload.columns, payload.rows || []));
      if ((payload.rows || []).length > 100) {
        appendBody(node, makeEl("div", "note muted", "表格仅渲染前 100 行，完整数据已参与归纳。"));
      }
    }
  }

  function renderSummarize(node, payload) {
    appendBody(node, kv([["模型", payload.model], ["输出字符", payload.chars]]));
    if (payload.message) appendBody(node, makeEl("div", "note muted", `流式输出异常：${payload.message}`));
  }

  /* ------------------------------------------------ 事件分发 */

  function handleStage(turn, event) {
    const node = ensureStage(turn, event.stage, event.payload?.round, event.status);
    setStageState(node, event.status, event.elapsed_ms);
    const payload = event.payload || {};
    if (event.status === "running") return;
    if (event.stage === "schema") renderSchema(node, payload);
    else if (event.stage === "generate") renderGenerate(node, payload);
    else if (event.stage === "check") renderCheck(node, payload);
    else if (event.stage === "execute") renderExecute(node, payload);
    else if (event.stage === "summarize") renderSummarize(node, payload);
    thread.scrollTop = thread.scrollHeight;
  }

  function handleDelta(turn, event) {
    turn.answerEl.style.display = "";
    turn.answerText += event.text || "";
    const html = renderText(turn.answerText);
    turn.answerTextEl.innerHTML = html;
    turn.answerTextEl.append(turn.caret);
    thread.scrollTop = thread.scrollHeight;
  }

  function handleDone(turn, event) {
    const payload = event.payload || {};
    turn.answerEl.style.display = "";
    if (!turn.answerText && payload.answer) {
      turn.answerText = payload.answer;
      turn.answerTextEl.innerHTML = renderText(payload.answer);
    }
    if (turn.caret && turn.caret.parentNode) turn.caret.remove();
    const usage = payload.usage || {};
    const parts = [
      `总耗时 ${fmtMs(payload.total_ms)}`,
      `复核 ${payload.rounds} 轮`,
      `${fmtNumber(usage.total_tokens || 0)} tokens`,
      `返回 ${payload.row_count ?? 0} 行`,
    ];
    for (const text of parts) turn.answerFootEl.append(makeEl("span", "", text));
    const headStat = $("#head-stat");
    headStat.textContent = `${fmtMs(payload.total_ms)} · ${payload.rounds} 轮复核\n${fmtNumber(usage.total_tokens || 0)} tokens`;
    thread.scrollTop = thread.scrollHeight;
  }

  function handleError(turn, event) {
    const payload = event.payload || {};
    const box = makeEl("div", "error-box");
    const title = makeEl("b", "", payload.fatal ? "请求被拒绝 · 只读模式" : "流程终止");
    box.append(title, document.createTextNode(payload.message || "未知错误"));
    if (payload.issues && payload.issues.length) {
      const ul = makeEl("ul", "issues");
      for (const issue of payload.issues) ul.append(makeEl("li", "", issue));
      box.append(ul);
    }
    turn.stagesEl.append(box);
    if (turn.caret && turn.caret.parentNode) turn.caret.remove();
    turn.answerEl.style.display = "none";
    thread.scrollTop = thread.scrollHeight;
  }

  /* ------------------------------------------------ 发送 */

  async function send(question) {
    if (running || !question.trim()) return;
    running = true;
    sendBtn.disabled = true;
    sendBtn.textContent = "生成中…";

    const turn = createTurn(question.trim());
    try {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      if (!res.ok || !res.body) {
        throw new Error(`HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          const line = block.split("\n").find((item) => item.startsWith("data: "));
          if (!line) continue;
          let event;
          try {
            event = JSON.parse(line.slice(6));
          } catch {
            continue;
          }
          if (event.type === "stage") handleStage(turn, event);
          else if (event.type === "delta") handleDelta(turn, event);
          else if (event.type === "done") handleDone(turn, event);
          else if (event.type === "error") handleError(turn, event);
        }
      }
    } catch (err) {
      const box = makeEl("div", "error-box");
      box.append(makeEl("b", "", "请求失败"), document.createTextNode(String(err)));
      turn.stagesEl.append(box);
    } finally {
      running = false;
      sendBtn.disabled = false;
      sendBtn.textContent = "发送";
    }
  }

  /* ------------------------------------------------ 绑定 */

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    input.value = "";
    input.style.height = "";
    send(question);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
  });

  $("#examples").addEventListener("click", (event) => {
    const chip = event.target.closest(".chip");
    if (!chip) return;
    input.value = chip.textContent.trim();
    input.focus();
  });

  loadHealth();
  loadSchema();
  input.focus();
})();
