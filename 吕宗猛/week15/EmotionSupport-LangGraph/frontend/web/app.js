(function () {
  "use strict";

  var chat = document.getElementById("chat");
  var welcome = document.getElementById("welcome");
  var composer = document.getElementById("composer");
  var input = document.getElementById("input");
  var sendBtn = document.getElementById("send");
  var statusBox = document.getElementById("status");
  var statusText = document.getElementById("status-text");
  var hint = document.getElementById("composer-hint");
  var sessionList = document.getElementById("session-list");
  var newChatBtn = document.getElementById("new-chat");
  var busy = false;
  var loadingMore = false;
  var suspendAutoScroll = false;
  var activeSessionId = null;
  var sessionPage = { beforeId: null, hasMore: false };
  var sessions = [];

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function scrollToBottom(force) {
    function stick() {
      chat.scrollTop = chat.scrollHeight;
      if (document.scrollingElement) {
        document.scrollingElement.scrollTop = document.scrollingElement.scrollHeight;
      }
    }
    stick();
    window.requestAnimationFrame(function () {
      stick();
      window.requestAnimationFrame(stick);
    });
    if (force) {
      window.setTimeout(stick, 120);
    }
  }

  if (window.MutationObserver) {
    var chatObserver = new MutationObserver(function () {
      if (!suspendAutoScroll) scrollToBottom();
    });
    chatObserver.observe(chat, { childList: true, subtree: true, characterData: true });
  }

  function setStatus(text, mode) {
    statusText.textContent = text;
    statusBox.className = "status" + (mode ? " " + mode : "");
  }

  function setBusy(value) {
    busy = value;
    sendBtn.disabled = value;
    composer.classList.toggle("is-busy", value);
  }

  function resetAgents() {
    var cards = document.querySelectorAll(".agent-card");
    for (var i = 0; i < cards.length; i++) {
      cards[i].classList.remove("active", "done");
    }
  }

  function highlightAgent(key, state) {
    var card = document.querySelector('.agent-card[data-agent="' + key + '"]');
    if (!card) return;
    if (state === "active") {
      card.classList.add("active");
      card.classList.remove("done");
    } else if (state === "done") {
      card.classList.remove("active");
      card.classList.add("done");
    }
  }

  function formatTime(value) {
    var date = new Date(value);
    if (isNaN(date.getTime())) return "";
    return date.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  function buildUserMessage(text) {
    var article = document.createElement("article");
    article.className = "msg user";
    var bubble = document.createElement("div");
    bubble.className = "bubble";
    var p = document.createElement("p");
    p.className = "user-text";
    p.textContent = text || "";
    bubble.appendChild(p);
    article.appendChild(bubble);
    return article;
  }

  function addUserMessage(text) {
    chat.appendChild(buildUserMessage(text));
    scrollToBottom(true);
  }

  function createAssistantMessage(userText) {
    var article = document.createElement("article");
    article.className = "msg assistant";
    article.innerHTML = [
      '<div class="avatar">屿</div>',
      '<div class="bubble">',
      '  <div class="trace">',
      '    <span class="trace-item active" data-trace="emotion"><i class="pulse"></i><span>情感识别 Agent</span></span>',
      '    <span class="trace-arrow">→</span>',
      '    <span class="trace-item muted" data-trace="reply"><span>等待路由</span></span>',
      '  </div>',
      '  <div class="emotion-panel hidden" data-emotion></div>',
      '  <div class="reply" data-reply></div>',
      '  <div class="done-banner hidden" data-done><span class="done-check">✓</span><span data-done-text>回应完成</span></div>',
      '  <div class="error-box hidden" data-error></div>',
      '</div>'
    ].join("");
    chat.appendChild(article);
    scrollToBottom(true);
    return {
      article: article,
      traceEmotion: article.querySelector('[data-trace="emotion"]'),
      traceReply: article.querySelector('[data-trace="reply"]'),
      emotionPanel: article.querySelector("[data-emotion]"),
      reply: article.querySelector("[data-reply]"),
      doneBanner: article.querySelector("[data-done]"),
      doneText: article.querySelector("[data-done-text]"),
      errorBox: article.querySelector("[data-error]"),
      userText: userText,
      completed: false
    };
  }

  function renderEmotion(panel, data) {
    panel.classList.remove("hidden");
    var label = data.label || "neutral";
    var pct = Math.round((Number(data.confidence) || 0) * 100);
    var keywords = Array.isArray(data.keywords) ? data.keywords : [];
    var html = [
      '<div class="emotion-head">',
      '  <span class="emotion-badge ' + escapeHtml(label) + '">' + escapeHtml(data.label_zh || label) + ' · ' + pct + '%</span>',
      '  <span class="emotion-intensity">强度 ' + escapeHtml(data.intensity == null ? "-" : data.intensity) + '/5</span>',
      '</div>',
      '<p class="emotion-reason">' + escapeHtml(data.reason || "已完成情感识别") + '</p>'
    ];
    if (keywords.length) {
      html.push('<div class="emotion-keywords">');
      for (var i = 0; i < keywords.length; i++) {
        html.push('<span class="keyword">' + escapeHtml(keywords[i]) + '</span>');
      }
      html.push("</div>");
    }
    panel.innerHTML = html.join("");
  }

  function buildStoredAssistant(message) {
    var meta = message.meta && typeof message.meta === "object" ? message.meta : {};
    var emotion = meta.emotion && typeof meta.emotion === "object" ? meta.emotion : null;
    var agentName = meta.agent_name || "回应 Agent";
    var article = document.createElement("article");
    article.className = "msg assistant";
    var bubble = document.createElement("div");
    bubble.className = "bubble";

    var trace = document.createElement("div");
    trace.className = "trace";
    var label = emotion && emotion.label_zh ? emotion.label_zh : "历史记录";
    trace.innerHTML = '<span class="trace-item done"><i class="pulse"></i><span>情感识别 · ' +
      escapeHtml(label) + '</span></span><span class="trace-arrow">→</span><span class="trace-item done"><span>' +
      escapeHtml(agentName) + '</span></span>';
    bubble.appendChild(trace);

    if (emotion) {
      var panel = document.createElement("div");
      panel.className = "emotion-panel";
      bubble.appendChild(panel);
      renderEmotion(panel, emotion);
    }

    var reply = document.createElement("div");
    reply.className = "reply";
    reply.textContent = message.content || "";
    bubble.appendChild(reply);

    var done = document.createElement("div");
    done.className = "done-banner";
    done.innerHTML = '<span class="done-check">✓</span><span>回应完成</span>';
    bubble.appendChild(done);

    var avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = "屿";
    article.appendChild(avatar);
    article.appendChild(bubble);
    return article;
  }

  function buildStoredMessage(message) {
    if (message.role === "user") {
      return buildUserMessage(message.content || "");
    }
    return buildStoredAssistant(message);
  }

  function clearMessages() {
    var nodes = chat.querySelectorAll(".msg, .load-more-bar, .error-box");
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].remove();
    }
  }

  function updateLoadMore() {
    var existing = chat.querySelector(".load-more-bar");
    if (existing) existing.remove();
    if (!activeSessionId || !sessionPage.hasMore) return;
    var bar = document.createElement("div");
    bar.className = "load-more-bar";
    var button = document.createElement("button");
    button.type = "button";
    button.className = "load-more-btn";
    button.textContent = "加载更早的 5 条";
    button.addEventListener("click", loadMore);
    bar.appendChild(button);
    var firstMessage = chat.querySelector(".msg");
    if (firstMessage) {
      chat.insertBefore(bar, firstMessage);
    } else {
      chat.appendChild(bar);
    }
  }

  function upsertSession(session) {
    if (!session || !session.id) return;
    var found = false;
    for (var i = 0; i < sessions.length; i++) {
      if (sessions[i].id === session.id) {
        sessions[i] = Object.assign({}, sessions[i], session);
        found = true;
        break;
      }
    }
    if (!found) sessions.unshift(session);
    sessions.sort(function (a, b) {
      return String(b.updated_at || "").localeCompare(String(a.updated_at || ""));
    });
  }

  function renderSessionList() {
    sessionList.innerHTML = "";
    if (!sessions.length) {
      var empty = document.createElement("div");
      empty.className = "session-empty";
      empty.textContent = "还没有会话记录";
      sessionList.appendChild(empty);
      return;
    }
    sessions.forEach(function (session) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "session-item" + (session.id === activeSessionId ? " active" : "");
      button.innerHTML = "<strong>" + escapeHtml(session.title || "新的对话") + "</strong><small>" +
        escapeHtml(formatTime(session.updated_at)) + " · " + (Number(session.message_count) || 0) + " 条</small>";
      button.addEventListener("click", function () {
        openSession(session.id);
      });
      sessionList.appendChild(button);
    });
  }

  async function loadSessions() {
    try {
      var response = await fetch("/api/sessions");
      if (!response.ok) return;
      var data = await response.json();
      sessions = Array.isArray(data.sessions) ? data.sessions : [];
      renderSessionList();
    } catch (ignored) {}
  }

  async function openSession(sessionId) {
    if (busy) return;
    activeSessionId = sessionId;
    sessionPage = { beforeId: null, hasMore: false };
    clearMessages();
    welcome.style.display = "none";
    resetAgents();
    renderSessionList();
    setStatus("加载会话…", "busy");
    try {
      var response = await fetch("/api/sessions/" + encodeURIComponent(sessionId) + "/messages?limit=5");
      var data = await response.json();
      if (!response.ok) throw new Error(data.detail || "加载会话失败");
      (data.messages || []).forEach(function (message) {
        chat.appendChild(buildStoredMessage(message));
      });
      sessionPage.beforeId = data.next_before_id;
      sessionPage.hasMore = Boolean(data.has_more);
      updateLoadMore();
      setStatus("已加载最近 5 条", "");
      scrollToBottom(true);
    } catch (error) {
      setStatus("加载失败", "error");
      var box = document.createElement("div");
      box.className = "error-box";
      box.textContent = error && error.message ? error.message : String(error);
      chat.appendChild(box);
    }
  }

  async function loadMore() {
    if (!activeSessionId || !sessionPage.hasMore || loadingMore) return;
    loadingMore = true;
    var button = chat.querySelector(".load-more-btn");
    if (button) button.disabled = true;
    var oldHeight = chat.scrollHeight;
    try {
      var response = await fetch(
        "/api/sessions/" + encodeURIComponent(activeSessionId) +
        "/messages?limit=5&before_id=" + encodeURIComponent(sessionPage.beforeId)
      );
      var data = await response.json();
      if (!response.ok) throw new Error(data.detail || "加载更多失败");
      suspendAutoScroll = true;
      var fragment = document.createDocumentFragment();
      (data.messages || []).forEach(function (message) {
        fragment.appendChild(buildStoredMessage(message));
      });
      var firstMessage = chat.querySelector(".msg");
      if (firstMessage) {
        chat.insertBefore(fragment, firstMessage);
      } else {
        chat.appendChild(fragment);
      }
      sessionPage.beforeId = data.next_before_id;
      sessionPage.hasMore = Boolean(data.has_more);
      updateLoadMore();
      var newHeight = chat.scrollHeight;
      chat.scrollTop += newHeight - oldHeight;
    } catch (error) {
      setStatus("加载更多失败", "error");
    } finally {
      loadingMore = false;
      window.setTimeout(function () { suspendAutoScroll = false; }, 0);
    }
  }

  function newChat() {
    if (busy) return;
    activeSessionId = null;
    sessionPage = { beforeId: null, hasMore: false };
    clearMessages();
    welcome.style.display = "";
    resetAgents();
    renderSessionList();
    setStatus("就绪", "");
    input.focus();
  }

  function showError(ctx, message) {
    if (ctx.doneBanner) {
      ctx.doneBanner.classList.add("hidden");
    }
    ctx.errorBox.classList.remove("hidden");
    ctx.errorBox.textContent = message || "发生了未知错误，请稍后再试。";
    ctx.traceEmotion.classList.remove("active");
    ctx.traceReply.classList.remove("active");
    setStatus("出错", "error");
    scrollToBottom(true);
  }

  function typeText(node, text) {
    return new Promise(function (resolve) {
      var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (reduced || !text) {
        node.textContent = text || "";
        resolve();
        return;
      }
      var index = 0;
      var step = Math.max(1, Math.ceil(text.length / 220));
      var timer = window.setInterval(function () {
        index += step;
        node.textContent = text.slice(0, index);
        scrollToBottom();
        if (index >= text.length) {
          window.clearInterval(timer);
          resolve();
        }
      }, 16);
    });
  }

  async function handleEvent(payload, ctx) {
    if (!payload || !payload.type) return;
    if (payload.type === "session") {
      if (payload.session && payload.session.id) {
        activeSessionId = payload.session.id;
        upsertSession(payload.session);
        renderSessionList();
      }
      return;
    }
    if (payload.type === "stage") {
      if (payload.stage === "emotion") {
        ctx.traceEmotion.classList.add("active");
        setStatus("正在识别情绪…", "busy");
      } else if (payload.stage === "reply") {
        ctx.traceEmotion.classList.remove("active");
        ctx.traceEmotion.classList.add("done");
        ctx.traceReply.classList.remove("muted");
        ctx.traceReply.classList.add("active");
        ctx.traceReply.textContent = payload.agent_name || "回应 Agent";
        highlightAgent("emotion", "done");
        highlightAgent(payload.agent, "active");
        setStatus("正在组织回应…", "busy");
      }
      return;
    }
    if (payload.type === "emotion") {
      renderEmotion(ctx.emotionPanel, payload);
      ctx.traceEmotion.classList.remove("active");
      ctx.traceEmotion.classList.add("done");
      ctx.traceEmotion.querySelector("span").textContent = "情感识别 · " + (payload.label_zh || payload.label);
      highlightAgent("emotion", "done");
      return;
    }
    if (payload.type === "reply") {
      ctx.traceReply.textContent = payload.agent_name || "回应 Agent";
      if (payload.text) {
        await typeText(ctx.reply, payload.text);
      }
      return;
    }
    if (payload.type === "done") {
      ctx.completed = true;
      if (payload.session_id) activeSessionId = payload.session_id;
      var seconds = ((Number(payload.elapsed_ms) || 0) / 1000).toFixed(1);
      var rounds = Number(payload.history_rounds) || 0;
      var doneSuffix = rounds ? " · " + rounds + "轮上下文" : "";
      setStatus("已完成 · " + seconds + "s" + doneSuffix, "done");
      if (ctx.doneBanner) {
        ctx.doneBanner.classList.remove("hidden");
        if (ctx.doneText) {
          ctx.doneText.textContent = "回应完成 · " + seconds + "s" + doneSuffix;
        }
      }
      if (payload.agent) highlightAgent(payload.agent, "done");
      var traceEmotion = ctx.traceEmotion.querySelector("span");
      if (payload.emotion && payload.emotion.label_zh) {
        traceEmotion.textContent = "情感识别 · " + payload.emotion.label_zh;
      }
      if (!ctx.reply.textContent && payload.reply) {
        ctx.reply.textContent = payload.reply;
      }
      loadSessions();
      scrollToBottom(true);
      return;
    }
    if (payload.type === "error") {
      showError(ctx, payload.message);
    }
  }

  async function sendMessage(text) {
    if (busy) return;
    var message = String(text || "").trim();
    if (!message) return;

    if (welcome) welcome.style.display = "none";
    addUserMessage(message);
    input.value = "";
    input.style.height = "";
    setBusy(true);
    setStatus("正在聆听…", "busy");
    resetAgents();
    highlightAgent("emotion", "active");
    var ctx = createAssistantMessage(message);

    try {
      var response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message, session_id: activeSessionId })
      });
      if (!response.ok || !response.body) {
        var detail = "";
        try {
          var errorBody = await response.json();
          detail = errorBody.detail || errorBody.message || "";
        } catch (ignored) {}
        throw new Error(detail || "服务返回 " + response.status);
      }

      var reader = response.body.getReader();
      var decoder = new TextDecoder("utf-8");
      var buffer = "";

      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        var blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";
        for (var i = 0; i < blocks.length; i++) {
          var block = blocks[i].trim();
          if (!block) continue;
          var lines = block.split("\n");
          for (var j = 0; j < lines.length; j++) {
            var line = lines[j].trim();
            if (line.indexOf("data:") !== 0) continue;
            var raw = line.slice(5).trim();
            if (!raw) continue;
            try {
              await handleEvent(JSON.parse(raw), ctx);
            } catch (parseError) {
              console.error("事件解析失败", parseError, raw);
            }
          }
        }
      }

      if (!ctx.completed) {
        setStatus("连接结束", "error");
      }
    } catch (error) {
      showError(ctx, error && error.message ? error.message : String(error));
    } finally {
      setBusy(false);
      input.focus();
      scrollToBottom(true);
    }
  }

  composer.addEventListener("submit", function (event) {
    event.preventDefault();
    sendMessage(input.value);
  });

  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage(input.value);
    }
  });

  input.addEventListener("input", function () {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  });

  var chips = document.querySelectorAll(".chip");
  for (var i = 0; i < chips.length; i++) {
    chips[i].addEventListener("click", function () {
      var text = this.getAttribute("data-text") || this.textContent || "";
      input.value = text;
      input.focus();
      input.dispatchEvent(new Event("input"));
    });
  }

  if (newChatBtn) {
    newChatBtn.addEventListener("click", newChat);
  }

  async function loadHealth() {
    try {
      var response = await fetch("/api/health");
      if (!response.ok) return;
      var data = await response.json();
      var emotionModel = document.getElementById("model-emotion");
      var replyModel = document.getElementById("model-reply");
      var modeBadge = document.getElementById("mode-badge");
      if (emotionModel && data.models) emotionModel.textContent = data.models.emotion || "—";
      if (replyModel && data.models) replyModel.textContent = data.models.reply || "—";
      if (data.status === "down") {
        if (modeBadge) { modeBadge.textContent = "后端未连接"; modeBadge.className = "mock"; }
        if (hint) { hint.textContent = "后端未启动，请先运行 backend/main.py"; }
        return;
      }
      if (modeBadge) {
        modeBadge.textContent = data.mock_mode ? "离线演示" : "真实模型";
        modeBadge.className = data.mock_mode ? "mock" : "";
      }
      if (data.mock_mode && hint) {
        hint.textContent = "离线演示模式 · 不调用真实模型";
      } else if (hint && data.history_rounds) {
        hint.textContent = "保留最近 " + data.history_rounds + " 轮上下文 · 情绪识别 → 条件路由 → 对应 Agent";
      }
    } catch (ignored) {}
  }

  loadSessions();
  loadHealth();
  input.focus();
})();
