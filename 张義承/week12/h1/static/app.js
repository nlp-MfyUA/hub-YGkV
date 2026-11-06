"use strict";

const els = {
  dropZone: document.getElementById("dropZone"),
  fileInput: document.getElementById("fileInput"),
  previewWrap: document.getElementById("previewWrap"),
  preview: document.getElementById("preview"),
  removeBtn: document.getElementById("removeBtn"),
  fileMeta: document.getElementById("fileMeta"),
  fileName: document.getElementById("fileName"),
  fileSize: document.getElementById("fileSize"),
  maxSize: document.getElementById("maxSize"),
  configWarning: document.getElementById("configWarning"),
  analyzeBtn: document.getElementById("analyzeBtn"),
  analyzeBtnText: document.getElementById("analyzeBtnText"),
  spinner: document.querySelector("#analyzeBtn .spinner"),
  clearBtn: document.getElementById("clearBtn"),
  status: document.getElementById("status"),
  emptyResult: document.getElementById("emptyResult"),
  emptyTitle: document.getElementById("emptyTitle"),
  emptySub: document.getElementById("emptySub"),
  result: document.getElementById("result"),
  levelPanel: document.getElementById("levelPanel"),
  levelText: document.getElementById("levelText"),
  levelHint: document.getElementById("levelHint"),
  sceneText: document.getElementById("sceneText"),
  elapsedText: document.getElementById("elapsedText"),
  modelText: document.getElementById("modelText"),
  riskList: document.getElementById("riskList"),
  reasonText: document.getElementById("reasonText"),
  footerModel: document.getElementById("footerModel"),
};

const ACCEPTED_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const LEVEL_CLASSES = ["level-high", "level-medium", "level-low", "level-none", "level-other"];
const LEVEL_CLASS = {
  "高风险": "level-high",
  "中风险": "level-medium",
  "低风险": "level-low",
  "无风险": "level-none",
  "非楼道": "level-other",
};
const LEVEL_HINTS = {
  "高风险": "发现可能直接起火的元素，请立即处理",
  "中风险": "存在可燃堆积或严重堵塞，建议尽快清理",
  "低风险": "存在轻微堆物，建议保持通道畅通",
  "无风险": "未发现明显消防安全隐患",
  "非楼道": "照片内容与住宅楼道无关",
};
const EMPTY_TITLE = "识别结果将显示在这里";
const EMPTY_SUB = "上传照片后点击「开始识别」";

const state = {
  file: null,
  objectUrl: null,
  busy: false,
  maxMb: 10,
};

function setStatus(message, isError = false) {
  els.status.textContent = message || "";
  els.status.classList.toggle("error", isError);
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function setEmptyStateLoading(loading) {
  els.emptyTitle.textContent = loading ? "模型正在识别…" : EMPTY_TITLE;
  els.emptySub.textContent = loading ? "通常需要 3–10 秒，请稍候" : EMPTY_SUB;
}

function resetResult() {
  els.result.classList.add("hidden");
  els.emptyResult.classList.remove("hidden");
  setEmptyStateLoading(false);
  els.levelPanel.classList.remove(...LEVEL_CLASSES);
  els.levelText.textContent = "";
  els.levelHint.textContent = "";
  els.sceneText.textContent = "";
  els.elapsedText.textContent = "";
  els.modelText.textContent = "";
  els.reasonText.textContent = "";
  els.riskList.replaceChildren();
}

function setBusy(busy) {
  state.busy = busy;
  const hasFile = Boolean(state.file);
  els.analyzeBtn.disabled = busy || !hasFile;
  els.clearBtn.disabled = busy || !hasFile;
  els.removeBtn.disabled = busy;
  els.analyzeBtn.setAttribute("aria-busy", String(busy));
  els.spinner.classList.toggle("hidden", !busy);
  els.analyzeBtnText.textContent = busy ? "识别中…" : "开始识别";
  els.dropZone.setAttribute("aria-disabled", String(busy));
}

function releaseObjectUrl() {
  if (state.objectUrl) {
    URL.revokeObjectURL(state.objectUrl);
    state.objectUrl = null;
  }
}

function clearAll() {
  if (state.busy) return;
  releaseObjectUrl();
  state.file = null;
  els.fileInput.value = "";
  els.preview.removeAttribute("src");
  els.previewWrap.classList.add("hidden");
  els.fileMeta.classList.add("hidden");
  els.dropZone.classList.remove("hidden", "dragover");
  els.fileName.textContent = "";
  els.fileSize.textContent = "";
  setBusy(false);
  resetResult();
  setStatus("");
}

function selectFile(file) {
  if (!file || state.busy) return;

  const looksLikeImage = ACCEPTED_TYPES.has(file.type) || /\.(jpe?g|png|webp)$/i.test(file.name);
  if (!looksLikeImage) {
    setStatus("仅支持 JPG、PNG、WebP 格式的图片。", true);
    return;
  }

  if (file.size > state.maxMb * 1024 * 1024) {
    setStatus(`图片超过 ${state.maxMb}MB 限制，请压缩后重试。`, true);
    return;
  }

  releaseObjectUrl();
  state.file = file;
  state.objectUrl = URL.createObjectURL(file);

  els.preview.src = state.objectUrl;
  els.preview.alt = `待识别照片：${file.name}`;
  els.previewWrap.classList.remove("hidden");
  els.dropZone.classList.add("hidden");
  els.fileMeta.classList.remove("hidden");
  els.fileName.textContent = file.name || "未命名图片";
  els.fileName.title = file.name || "";
  els.fileSize.textContent = formatSize(file.size);

  resetResult();
  setBusy(false);
  setStatus("图片已就绪，点击「开始识别」。");
}

function renderResult(data) {
  const level = typeof data.level === "string" ? data.level : "非楼道";

  els.emptyResult.classList.add("hidden");
  els.result.classList.remove("hidden");

  els.levelPanel.classList.remove(...LEVEL_CLASSES);
  els.levelPanel.classList.add(LEVEL_CLASS[level] || "level-other");
  els.levelText.textContent = level;
  els.levelHint.textContent = LEVEL_HINTS[level] || "";

  els.sceneText.textContent = data.scene || "—";
  els.sceneText.title = data.scene || "";
  const elapsed = Number(data.elapsed_ms);
  els.elapsedText.textContent = Number.isFinite(elapsed) ? `${(elapsed / 1000).toFixed(1)} 秒` : "—";
  els.modelText.textContent = data.model || "—";
  els.modelText.title = data.model || "";

  els.riskList.replaceChildren();
  const risks = Array.isArray(data.risks) ? data.risks.filter((item) => typeof item === "string") : [];
  if (risks.length === 0) {
    const item = document.createElement("li");
    item.className = "empty";
    item.textContent = level === "非楼道" ? "非楼道场景，不适用隐患评级" : "未发现明显隐患";
    els.riskList.append(item);
  } else {
    for (const risk of risks) {
      const item = document.createElement("li");
      item.textContent = risk;
      els.riskList.append(item);
    }
  }

  els.reasonText.textContent = data.reason || "模型未提供判断理由。";
}

async function analyze() {
  if (!state.file || state.busy) return;

  setBusy(true);
  setStatus("模型正在识别，请稍候…");
  resetResult();
  setEmptyStateLoading(true);

  const formData = new FormData();
  formData.append("file", state.file, state.file.name || "photo");

  try {
    const response = await fetch("/api/analyze", { method: "POST", body: formData });
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      // 非 JSON 响应时使用状态码提示。
    }

    if (!response.ok) {
      const detail = payload && typeof payload.detail === "string" ? payload.detail : "";
      throw new Error(detail || `识别请求失败（HTTP ${response.status}）。`);
    }

    renderResult(payload);
    setStatus("识别完成。");
  } catch (error) {
    setEmptyStateLoading(false);
    setStatus(error instanceof Error ? error.message : "识别失败，请稍后重试。", true);
  } finally {
    setBusy(false);
  }
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    if (!response.ok) return;
    const info = await response.json();

    if (Number.isFinite(Number(info.max_image_mb)) && Number(info.max_image_mb) >= 1) {
      state.maxMb = Number(info.max_image_mb);
      els.maxSize.textContent = String(state.maxMb);
    }
    if (typeof info.model === "string" && info.model) {
      els.footerModel.textContent = info.model;
    }
    if (info.key_configured === false) {
      els.configWarning.textContent =
        "服务端未配置 DEEPSEEK_API_KEY，识别请求会失败。请在 .env 或环境变量中设置后重启服务。";
      els.configWarning.classList.remove("hidden");
    }
  } catch {
    // 健康检查失败不阻塞页面，识别时会给出错误提示。
  }
}

els.dropZone.addEventListener("click", () => {
  if (!state.busy) els.fileInput.click();
});

els.dropZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    if (!state.busy) els.fileInput.click();
  }
});

els.fileInput.addEventListener("change", () => {
  const file = els.fileInput.files && els.fileInput.files[0];
  if (file) selectFile(file);
});

["dragenter", "dragover"].forEach((eventName) => {
  els.dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    if (!state.busy) els.dropZone.classList.add("dragover");
  });
});

["dragleave", "dragend"].forEach((eventName) => {
  els.dropZone.addEventListener(eventName, () => {
    els.dropZone.classList.remove("dragover");
  });
});

els.dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  els.dropZone.classList.remove("dragover");
  const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
  if (file) selectFile(file);
});

window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", (event) => event.preventDefault());

els.removeBtn.addEventListener("click", clearAll);
els.clearBtn.addEventListener("click", clearAll);
els.analyzeBtn.addEventListener("click", analyze);

window.addEventListener("beforeunload", releaseObjectUrl);

setBusy(false);
loadHealth();
