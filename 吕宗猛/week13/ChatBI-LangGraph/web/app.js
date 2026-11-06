/* ChatBI · 对话问数（LangGraph 版）前端逻辑。
 *
 * 数据流：POST /api/chat/stream {question, history} → SSE 事件
 *   {type:"stage", stage, status, elapsed_ms, payload}  五个阶段的进度
 *   {type:"delta", stage:"summarize", text}             归纳流式增量
 *   {type:"done",  payload}                             最终结果（答案/SQL/行数/耗时/tokens）
 *   {type:"error", payload}                             终止性错误
 * 事件契约与 week12 完全一致；前端额外维护最近几轮问答随下次请求回传，支持追问。
 */

(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);

  const chat = $("#chat");
  const empty = $("#empty");
  const form = $("#composer");
  const input = $("#input");
  const sendBtn = $("#send");
  const stopBtn = $("#stop");

  const STAGE_ORDER = ["schema", "generate", "check", "execute", "summarize"];
  const STAGE_TITLES = {
    schema: "解析结构",
    generate: "生成 SQL",
    check: "复核",
    execute: "执行",
    summarize: "归纳",
  };

  /** 已完成问答（成功才入列），发送时取最近 3 条随请求回传 */
  const turns = [];
  let running = false;
  let controller = null;

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

  const fmtNumber = (value) =>
    new Intl.NumberFormat("zh-CN").format(Number(value) || 0);

  const NUM_RE = /^-?\d[\d,]*(\.\d+)?$/;

  /* 行内渲染：转义 + `code` + **加粗**（归纳答案被要求是纯文本，保持轻量） */
  const inline = (escaped) =>
    escaped
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

  function makeEl(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function resultTable(columns, rows) {
    const wrap = makeEl("div", "table-wrap");
    const table = document.createElement("table");
    table.className = "grid";
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const col of columns) headRow.append(makeEl("th", "", col));
    thead.append(headRow);
    const tbody = document.createElement("tbody");
    for (const row of rows) {
      const tr = document.createElement("tr");
      for (const cell of row) {
        const text = cell === null ? "NULL" : String(cell);
        tr.append(makeEl("td", NUM_RE.test(text) ? "num" : "", text));
      }
      tbody.append(tr);
    }
    table.append(thead, tbody);
    wrap.append(table);
    return wrap;
  }

  function scrollToBottom() {
    chat.scrollTop = chat.scrollHeight;
  }

  /* ------------------------------------------------ 气泡构建 */

  function addUserMsg(question) {
    empty.remove();
    const bubble = makeEl("div", "msg-user", question);
    chat.append(bubble);
    scrollToBottom();
  }

  function buildBotBubble() {
    const bubble = makeEl("div", "msg-bot");
    const stages = makeEl("div", "stages");
    const pills = {};
    for (const stage of STAGE_ORDER) {
      const pill = makeEl("span", "stage-pill");
      pill.append(makeEl("span", "dot"));
      pill.append(makeEl("span", "name", STAGE_TITLES[stage]));
      const dur = makeEl("span", "dur");
      pill.append(dur);
      stages.append(pill);
      pills[stage] = { pill, dur };
    }
    const answer = makeEl("div", "answer streaming");
    const extra = makeEl("div");
    const detail = document.createElement("details");
    detail.className = "detail";
    const summary = makeEl("summary", "", "执行详情（SQL / 数据表 / 统计）");
    const detailBody = makeEl("div", "detail-body");
    detail.append(summary, detailBody);
    bubble.append(stages, answer, extra, detail);
    chat.append(bubble);
    scrollToBottom();
    return { bubble, pills, answer, extra, detailBody, detail };
  }

  function setPill(pills, stage, status, elapsedMs, note) {
    const item = pills[stage];
    if (!item) return;
    item.pill.className = `stage-pill ${status}`;
    // 执行中只显示「…」，避免误读成「已完成，耗时 0ms」；完毕后显示最终耗时
    item.dur.textContent =
      status === "running"
        ? "…"
        : [elapsedMs !== undefined && elapsedMs !== null ? fmtMs(elapsedMs) : "", note || ""]
            .filter(Boolean)
            .join(" · ");
  }

  /* ------------------------------------------------ SSE 消费 */

  function buildHistory() {
    return turns.slice(-3).map((turn) => ({
      question: turn.question,
      sql: turn.sql || "",
      answer: turn.answer || "",
    }));
  }

  async function ask(question) {
    if (running || !question.trim()) return;
    running = true;
    sendBtn.disabled = true;
    stopBtn.hidden = false;
    addUserMsg(question.trim());

    const ui = buildBotBubble();
    let sql = "";
    let roundNote = 0;
    let rowCount = 0;
    let lastColumns = null; // 表格数据在 execute 阶段的 stage 事件里，暂存到 done 一起渲染
    let lastRows = null;
    controller = new AbortController();

    const finish = () => {
      ui.answer.classList.remove("streaming");
      running = false;
      controller = null;
      sendBtn.disabled = false;
      stopBtn.hidden = true;
    };

    const showError = (message) => {
      ui.extra.replaceChildren(makeEl("div", "notice err", message));
      finish();
      scrollToBottom();
    };

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question.trim(), history: buildHistory() }),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let index;
        while ((index = buffer.indexOf("\n\n")) >= 0) {
          const raw = buffer.slice(0, index).trim();
          buffer = buffer.slice(index + 2);
          if (!raw.startsWith("data:")) continue;
          let event;
          try {
            event = JSON.parse(raw.slice(5).trim());
          } catch {
            continue;
          }
          handleEvent(event);
        }
      }
    } catch (err) {
      if (err.name === "AbortError") {
        ui.extra.append(makeEl("div", "notice warn", "已停止本次问答（结果未完整生成）。"));
        ui.answer.classList.remove("streaming");
      } else {
        showError(`请求失败：${err.message || err}`);
      }
    } finally {
      if (running) finish();
    }

    function handleEvent(event) {
      if (event.type === "stage") {
        const { stage, status, elapsed_ms: elapsedMs, payload } = event;
        if (stage === "execute" && status === "done" && payload.columns) {
          lastColumns = payload.columns;
          lastRows = payload.rows || [];
        }
        let note = "";
        if (stage === "generate" && status === "done" && payload.round) {
          note = `第 ${payload.round} 轮`;
          roundNote = Math.max(roundNote, payload.round);
        }
        if (stage === "check") {
          if (status === "done") {
            note = payload.approved
              ? `通过${payload.round ? `（第 ${payload.round} 轮）` : ""}`
              : `未通过${payload.round ? `（第 ${payload.round} 轮）` : ""}`;
            if (!payload.approved && payload.issues && payload.issues.length) {
              setPill(ui.pills, stage, "error", elapsedMs, note);
            } else {
              setPill(ui.pills, stage, status, elapsedMs, note);
            }
            if (!payload.approved && payload.source === "static" && payload.fatal) {
              // fatal 由后续 error 事件呈现，这里只更新徽章
            }
            scrollToBottom();
            return;
          }
        }
        setPill(ui.pills, stage, status, elapsedMs, note);
        scrollToBottom();
        return;
      }

      if (event.type === "delta") {
        ui.answer.textContent += event.text;
        scrollToBottom();
        return;
      }

      if (event.type === "error") {
        setPill(ui.pills, event.payload.stage, "error", undefined, "失败");
        showError(event.payload.message || "执行失败");
        return;
      }

      if (event.type === "done") {
        const payload = event.payload || {};
        sql = payload.sql || sql;
        // 定稿：答案区换正式渲染（流式文本已一致，补行内格式）
        ui.answer.innerHTML = inline(escapeHtml(payload.answer || ui.answer.textContent));

        ui.detailBody.replaceChildren();
        if (sql) {
          const sqlBox = makeEl("div");
          sqlBox.append(makeEl("div", "block-label", "最终 SQL"));
          const pre = document.createElement("pre");
          pre.className = "sql-block";
          pre.textContent = sql;
          sqlBox.append(pre);
          ui.detailBody.append(sqlBox);
        }
        if (lastColumns && lastColumns.length) {
          const tableBox = makeEl("div");
          const label = `查询结果（${payload.row_count || lastRows.length} 行${payload.truncated ? `，已达上限 ${payload.max_rows || 200} 行` : ""}）`;
          tableBox.append(makeEl("div", "block-label", label));
          tableBox.append(resultTable(lastColumns, lastRows || []));
          ui.detailBody.append(tableBox);
          rowCount = payload.row_count || lastRows.length;
        }
        const meta = makeEl("div", "meta-row");
        const usage = payload.usage || {};
        const chips = [
          `${payload.rounds || roundNote} 轮复核`,
          `总耗时 ${fmtMs(payload.total_ms)}`,
          `${fmtNumber(usage.total_tokens || 0)} tokens`,
        ];
        for (const text of chips) meta.append(makeEl("span", "meta-chip", text));
        ui.detailBody.append(meta);
        ui.detail.style.display = "";
        ui.detail.open = false;

        // 成功入列：供后续追问携带上下文
        turns.push({
          question: question.trim(),
          sql,
          answer: payload.answer || ui.answer.textContent,
        });

        ui.answer.classList.remove("streaming");
        finish();
        scrollToBottom();
      }
    }
  }

  /* ------------------------------------------------ 事件绑定 */

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question || running) return;
    input.value = "";
    ask(question);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  stopBtn.addEventListener("click", () => {
    if (controller) controller.abort();
  });

  $("#examples").addEventListener("click", (event) => {
    const chip = event.target.closest(".chip");
    if (!chip || running) return;
    ask(chip.textContent.trim());
  });

  /* ------------------------------------------------ 顶栏元信息 */

  (async () => {
    const meta = $("#top-meta");
    try {
      const response = await fetch("/api/health");
      const data = await response.json();
      const schemaInfo = data.schema || {};
      const range = schemaInfo.data_range || "";
      meta.textContent = [
        "chinook.db",
        schemaInfo.table_count ? `${schemaInfo.table_count} 表` : "",
        range,
        `网关 ${data.base_url || ""}`,
      ].filter(Boolean).join(" · ");
    } catch {
      meta.textContent = "健康检查失败，服务可能未就绪";
    }
  })();
})();
