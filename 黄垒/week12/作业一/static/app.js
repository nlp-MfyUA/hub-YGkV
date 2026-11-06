/* ============================================================
   楼道消防隐患识别 · 前端逻辑
   - 拍照（系统相机 / getUserMedia）/ 上传 / 拖拽
   - 上传前压缩，调用 /api/analyze
   - 渲染五级结果、本地浏览记录
   ============================================================ */

const MAX_UPLOAD_MB = 10;
const HISTORY_KEY = "corridor-risk-history-v1";
const HISTORY_LIMIT = 8;
const LEVEL_COLOR_VAR = {
  高风险: "--high",
  中风险: "--medium",
  低风险: "--low",
  无风险: "--safe",
  非楼道: "--none",
};

const $ = (id) => document.getElementById(id);

const el = {
  stage: $("stage"),
  stageEmpty: $("stageEmpty"),
  video: $("video"),
  preview: $("preview"),
  loading: $("loading"),
  loadingText: $("loadingText"),
  fileCapture: $("fileCapture"),
  fileUpload: $("fileUpload"),
  btnCapture: $("btnCapture"),
  btnUpload: $("btnUpload"),
  btnLive: $("btnLive"),
  btnRetake: $("btnRetake"),
  btnShutter: $("btnShutter"),
  btnAnalyze: $("btnAnalyze"),
  modelChip: $("modelChip"),
  modelText: $("modelText"),
  resultSection: $("resultSection"),
  resultHeading: $("resultHeading"),
  resultSummary: $("resultSummary"),
  levelBadge: $("levelBadge"),
  levelText: $("levelText"),
  scoreValue: $("scoreValue"),
  meterFill: $("meterFill"),
  confidenceValue: $("confidenceValue"),
  findingsList: $("findingsList"),
  suggestionsList: $("suggestionsList"),
  resultMeta: $("resultMeta"),
  rawJson: $("rawJson"),
  historySection: $("historySection"),
  historyList: $("historyList"),
  btnClearHistory: $("btnClearHistory"),
};

const state = {
  file: null,
  objectUrl: null,
  stream: null,
  busy: false,
  loadingTimer: null,
};

/* ----------------------------- 初始化 ----------------------------- */

checkHealth();
bindEvents();
renderHistory();

function bindEvents() {
  el.btnCapture.addEventListener("click", () => el.fileCapture.click());
  el.btnUpload.addEventListener("click", () => el.fileUpload.click());
  el.btnLive.addEventListener("click", startLive);

  el.fileCapture.addEventListener("change", onFilePicked);
  el.fileUpload.addEventListener("change", onFilePicked);
  el.btnShutter.addEventListener("click", captureFrame);
  el.btnRetake.addEventListener("click", resetStage);
  el.btnAnalyze.addEventListener("click", analyze);
  el.btnClearHistory.addEventListener("click", clearHistory);

  el.stage.addEventListener("dragover", (event) => {
    event.preventDefault();
    el.stage.classList.add("dragging");
  });
  el.stage.addEventListener("dragleave", () => el.stage.classList.remove("dragging"));
  el.stage.addEventListener("drop", (event) => {
    event.preventDefault();
    el.stage.classList.remove("dragging");
    const file = event.dataTransfer?.files?.[0];
    if (file) handleFile(file);
  });

  window.addEventListener("pagehide", stopCamera);
}

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    if (data.ok) {
      el.modelChip.classList.add("ready");
      el.modelText.textContent = `${data.provider} · ${data.model}`;
    } else {
      el.modelChip.classList.add("error");
      el.modelText.textContent = "模型未配置";
    }
  } catch {
    el.modelChip.classList.add("error");
    el.modelText.textContent = "服务未连接";
  }
}

/* ----------------------------- 取图 ----------------------------- */

async function onFilePicked(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (file) await handleFile(file);
}

async function handleFile(file) {
  if (!file.type.startsWith("image/")) {
    toast("请选择图片文件（JPG / PNG / WEBP）");
    return;
  }
  stopCamera();
  // 超大图片先尝试压缩，压完仍超限再拒绝
  let prepared = file;
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    prepared = await compressImage(file, 1600, 0.8);
  }
  if (prepared.size > MAX_UPLOAD_MB * 1024 * 1024) {
    toast(`图片超过 ${MAX_UPLOAD_MB}MB，请换一张或先压缩`);
    return;
  }

  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.file = prepared;
  state.objectUrl = URL.createObjectURL(prepared);

  el.preview.src = state.objectUrl;
  el.preview.hidden = false;
  el.stageEmpty.hidden = true;
  el.stage.dataset.state = "preview";

  el.btnShutter.hidden = true;
  el.btnRetake.hidden = false;
  el.btnAnalyze.disabled = false;
  el.resultSection.hidden = true;
  el.stage.scrollIntoView({ behavior: "smooth", block: "center" });
}

function resetStage() {
  stopCamera();
  state.file = null;
  if (state.objectUrl) {
    URL.revokeObjectURL(state.objectUrl);
    state.objectUrl = null;
  }
  el.preview.removeAttribute("src");
  el.preview.hidden = true;
  el.video.hidden = true;
  el.stageEmpty.hidden = false;
  el.stage.dataset.state = "empty";
  el.btnRetake.hidden = true;
  el.btnShutter.hidden = true;
  el.btnAnalyze.disabled = true;
  el.loading.hidden = true;
}

/* ----------------------------- 摄像头 ----------------------------- */

async function startLive() {
  if (!navigator.mediaDevices?.getUserMedia) {
    toast("当前浏览器不支持网页摄像头，已切换为系统相机");
    el.fileCapture.click();
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 } },
      audio: false,
    });
    state.stream = stream;
    el.video.srcObject = stream;
    el.video.hidden = false;
    el.preview.hidden = true;
    el.stageEmpty.hidden = true;
    el.stage.dataset.state = "video";
    el.btnShutter.hidden = false;
    el.btnRetake.hidden = false;
    el.btnAnalyze.disabled = true;
    await el.video.play();
  } catch (error) {
    console.warn("getUserMedia 失败：", error);
    toast("无法打开网页摄像头，已切换为系统相机");
    el.fileCapture.click();
  }
}

function stopCamera() {
  if (state.stream) {
    state.stream.getTracks().forEach((track) => track.stop());
    state.stream = null;
  }
  if (el.video.srcObject) el.video.srcObject = null;
  el.video.hidden = true;
}

async function captureFrame() {
  const video = el.video;
  if (!video.videoWidth) {
    toast("摄像头还没有准备好，请稍等");
    return;
  }

  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext("2d").drawImage(video, 0, 0);

  const blob = await new Promise((resolve) =>
    canvas.toBlob(resolve, "image/jpeg", 0.9)
  );
  if (!blob) {
    toast("拍照失败，请重试");
    return;
  }

  await handleFile(new File([blob], `camera-${Date.now()}.jpg`, { type: "image/jpeg" }));
}

/* ----------------------------- 压缩 ----------------------------- */

async function compressImage(file, maxSide = 1600, quality = 0.88) {
  if (file.size <= 1.2 * 1024 * 1024) return file;

  try {
    const bitmap = await loadBitmap(file);
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    if (scale === 1 && file.size <= 2.5 * 1024 * 1024) return file;

    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);

    const blob = await new Promise((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", quality)
    );
    if (!blob) return file;
    return new File([blob], file.name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" });
  } catch (error) {
    console.warn("前端压缩失败，使用原图：", error);
    return file;
  }
}

function loadBitmap(file) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    const url = URL.createObjectURL(file);
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("图片解码失败"));
    };
    image.src = url;
  });
}

/* ----------------------------- 识别 ----------------------------- */

async function analyze() {
  if (!state.file || state.busy) return;

  state.busy = true;
  el.btnAnalyze.disabled = true;
  el.btnRetake.disabled = true;
  el.btnCapture.disabled = true;
  el.btnUpload.disabled = true;
  startLoading();

  const form = new FormData();
  form.append("file", state.file, state.file.name || "corridor.jpg");

  try {
    const response = await fetch("/api/analyze", { method: "POST", body: form });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || `识别失败（HTTP ${response.status}）`);
    }

    state.lastResult = payload;
    renderResult(payload.data, payload.meta);
    saveHistory(state.objectUrl, payload.data, payload.meta);
    el.resultSection.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    toast(error.message || "识别失败，请稍后再试");
  } finally {
    stopLoading();
    state.busy = false;
    el.btnAnalyze.disabled = false;
    el.btnRetake.disabled = false;
    el.btnCapture.disabled = false;
    el.btnUpload.disabled = false;
  }
}

function startLoading() {
  const steps = [
    "正在上传图片…",
    "模型正在观察画面…",
    "正在按五级标准判定…",
    "正在生成处置建议…",
  ];
  let index = 0;
  el.loading.hidden = false;
  el.loadingText.textContent = steps[0];
  clearInterval(state.loadingTimer);
  state.loadingTimer = setInterval(() => {
    index = Math.min(index + 1, steps.length - 1);
    el.loadingText.textContent = steps[index];
  }, 3500);
}

function stopLoading() {
  clearInterval(state.loadingTimer);
  state.loadingTimer = null;
  el.loading.hidden = true;
}

/* ----------------------------- 渲染结果 ----------------------------- */

function renderResult(data, meta) {
  const level = data.risk_level;

  el.levelBadge.dataset.level = level;
  el.levelText.textContent = level;
  el.resultHeading.textContent = headingFor(level);
  el.resultSummary.textContent = data.summary || "（模型未给出结论）";

  const score = Number(data.risk_score) || 0;
  el.scoreValue.textContent = score;
  el.meterFill.style.width = `${Math.max(2, score)}%`;
  el.confidenceValue.textContent = `${Math.round((Number(data.confidence) || 0) * 100)}%`;

  renderFindings(data.findings);
  renderSuggestions(data.suggestions);
  renderReviewFlag(data.need_human_review);

  el.resultMeta.replaceChildren(
    metaItem(meta.provider + " · " + meta.model),
    metaItem(`耗时 ${(meta.latency_ms / 1000).toFixed(1)}s`),
    metaItem(`压缩后 ${(meta.image_bytes / 1024).toFixed(0)}KB · ${meta.image_size}`),
    metaItem(`请求 ${meta.request_id}`),
    metaItem(formatTime(meta.timestamp))
  );

  el.rawJson.textContent = JSON.stringify({ data, meta }, null, 2);
  el.resultSection.hidden = false;
}

function headingFor(level) {
  return {
    高风险: "发现高风险消防隐患",
    中风险: "存在中等消防隐患",
    低风险: "存在轻微堆物现象",
    无风险: "通道状态良好",
    非楼道: "这不是楼道场景",
  }[level] || "识别结论";
}

function renderFindings(findings) {
  el.findingsList.replaceChildren();
  if (!findings || !findings.length) {
    el.findingsList.appendChild(noteItem("画面中未发现明显的隐患元素。"));
    return;
  }
  for (const finding of findings) {
    const item = document.createElement("li");

    const dot = document.createElement("span");
    dot.className = "f-sev";
    dot.dataset.sev = finding.severity || "low";

    const body = document.createElement("div");
    body.className = "f-body";

    const category = document.createElement("div");
    category.className = "f-cat";
    category.textContent = finding.category || "其它";

    const desc = document.createElement("div");
    desc.className = "f-desc";
    desc.textContent = finding.description || "（无描述）";

    body.append(category, desc);
    item.append(dot, body);
    el.findingsList.appendChild(item);
  }
}

function renderSuggestions(suggestions) {
  el.suggestionsList.replaceChildren();
  if (!suggestions || !suggestions.length) {
    el.suggestionsList.appendChild(noteItem("非楼道图片，无需给出处置建议。"));
    return;
  }
  for (const text of suggestions) {
    const item = document.createElement("li");
    item.textContent = text;
    el.suggestionsList.appendChild(item);
  }
}

function renderReviewFlag(needReview) {
  const existing = document.querySelector(".review-flag");
  if (existing) existing.remove();
  if (!needReview) return;

  const flag = document.createElement("div");
  flag.className = "review-flag";
  flag.textContent = "画面信息不足，模型建议人工到现场复核后再处置。";
  el.resultSection.querySelector(".score-row").after(flag);
}

function noteItem(text) {
  const item = document.createElement("li");
  item.className = "empty-note";
  item.textContent = text;
  return item;
}

function metaItem(text) {
  const span = document.createElement("span");
  span.textContent = text;
  return span;
}

function formatTime(isoString) {
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return isoString;
  return date.toLocaleString("zh-CN", { hour12: false });
}

/* ----------------------------- 历史记录 ----------------------------- */

async function saveHistory(imageUrl, data, meta) {
  if (!imageUrl) return;
  try {
    const thumb = await makeThumbnail(imageUrl);
    const record = {
      id: meta.request_id,
      time: meta.timestamp,
      level: data.risk_level,
      summary: data.summary,
      thumb,
      data,
      meta,
    };
    const list = readHistory().filter((item) => item.id !== record.id);
    list.unshift(record);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, HISTORY_LIMIT)));
    renderHistory();
  } catch (error) {
    console.warn("保存浏览记录失败：", error);
  }
}

function makeThumbnail(src) {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      const size = 160;
      canvas.width = size;
      canvas.height = size;
      const context = canvas.getContext("2d");
      const scale = Math.max(size / image.width, size / image.height);
      const width = image.width * scale;
      const height = image.height * scale;
      context.drawImage(image, (size - width) / 2, (size - height) / 2, width, height);
      resolve(canvas.toDataURL("image/jpeg", 0.7));
    };
    image.onerror = () => resolve("");
    image.src = src;
  });
}

function readHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

function renderHistory() {
  const list = readHistory();
  el.historySection.hidden = list.length === 0;
  el.historyList.replaceChildren();

  for (const record of list) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "history-card";
    card.addEventListener("click", () => {
      if (record.thumb) {
        el.preview.src = record.thumb;
        el.preview.hidden = false;
        el.stageEmpty.hidden = true;
        el.stage.dataset.state = "preview";
        el.btnRetake.hidden = false;
      }
      // 浏览历史只用于回看结论，不能直接再次识别
      state.file = null;
      el.btnAnalyze.disabled = true;
      el.btnShutter.hidden = true;
      renderResult(record.data, record.meta);
      el.resultSection.scrollIntoView({ behavior: "smooth", block: "start" });
    });

    const image = document.createElement("img");
    image.src = record.thumb || "";
    image.alt = "";

    const body = document.createElement("div");
    body.className = "history-body";

    const level = document.createElement("div");
    level.className = "history-level";
    level.dataset.level = record.level;
    level.textContent = record.level;
    level.style.color = `var(${LEVEL_COLOR_VAR[record.level] || "--text-2"})`;

    const summary = document.createElement("div");
    summary.className = "history-summary";
    summary.textContent = record.summary || "";

    body.append(level, summary);
    card.append(image, body);
    el.historyList.appendChild(card);
  }
}

function clearHistory() {
  localStorage.removeItem(HISTORY_KEY);
  renderHistory();
}

/* ----------------------------- 提示 ----------------------------- */

let toastTimer = null;

function toast(message, type = "error") {
  let node = document.querySelector(".toast");
  if (!node) {
    node = document.createElement("div");
    node.className = "toast";
    node.setAttribute("role", "status");
    document.body.appendChild(node);
  }
  node.textContent = message;
  node.dataset.type = type;
  requestAnimationFrame(() => node.classList.add("show"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("show"), 4200);
}
