/* 楼道消防安全风险识别 —— 前端逻辑 */

const $ = (id) => document.getElementById(id);

const els = {
  preview: $("preview"),
  previewImg: $("previewImg"),
  previewEmpty: $("previewEmpty"),
  cameraInput: $("cameraInput"),
  albumInput: $("albumInput"),
  analyzeBtn: $("analyzeBtn"),
  annotateToggle: $("annotateToggle"),
  providerSelect: $("providerSelect"),
  providerBadge: $("providerBadge"),
  resultCard: $("resultCard"),
  riskHead: $("riskHead"),
  riskLevel: $("riskLevel"),
  riskScore: $("riskScore"),
  meterFill: $("meterFill"),
  reviewTip: $("reviewTip"),
  metaHallway: $("metaHallway"),
  metaHazards: $("metaHazards"),
  metaModel: $("metaModel"),
  obsList: $("obsList"),
  reasonText: $("reasonText"),
  adviceBlock: $("adviceBlock"),
  adviceList: $("adviceList"),
  historyList: $("historyList"),
  refreshHistory: $("refreshHistory"),
  loading: $("loading"),
  loadingHint: $("loadingHint"),
  toast: $("toast"),
};

const LIBELS = {
  none: "无风险",
  low: "低风险",
  medium: "中风险",
  high: "高风险",
  non_hallway: "非楼道",
};

const COLORS = {
  none: "#1a9c5b",
  low: "#c8a415",
  medium: "#e8722c",
  high: "#d8342f",
  non_hallway: "#7a8699",
};

let selectedFile = null;

/* ---------------------------------------------------------------- 工具 */
function toast(msg, ms = 2600) {
  els.toast.textContent = msg;
  els.toast.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (els.toast.hidden = true), ms);
}

function showLoading(on, hint) {
  els.loading.hidden = !on;
  if (hint) els.loadingHint.textContent = hint;
}

/* ---------------------------------------------------------------- 读图 */
function handleFile(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    toast("请选择图片文件");
    return;
  }
  if (file.size > 30 * 1024 * 1024) {
    toast("图片过大，请换一张（超过 30MB）");
    return;
  }

  selectedFile = file;
  const url = URL.createObjectURL(file);
  els.previewImg.src = url;
  els.previewImg.hidden = false;
  els.previewEmpty.hidden = true;
  els.analyzeBtn.disabled = false;
  els.resultCard.hidden = true;
}

els.cameraInput.addEventListener("change", (e) => {
  handleFile(e.target.files[0]);
  e.target.value = ""; // 允许重复选择同一张
});
els.albumInput.addEventListener("change", (e) => {
  handleFile(e.target.files[0]);
  e.target.value = "";
});

/* ---------------------------------------------- 前端压缩（省流量、防超时） */
async function compress(file, maxEdge = 1600, quality = 0.85) {
  // 手机上 12MP 原图直接传会很慢，先在本机缩到长边 1600
  try {
    const bitmap = await createImageBitmap(file);
    const { width, height } = bitmap;
    const scale = Math.min(1, maxEdge / Math.max(width, height));
    if (scale === 1 && file.size < 2 * 1024 * 1024) {
      bitmap.close?.();
      return file;
    }

    const canvas = document.createElement("canvas");
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close?.();

    const blob = await new Promise((r) => canvas.toBlob(r, "image/jpeg", quality));
    return new File([blob], "upload.jpg", { type: "image/jpeg" });
  } catch (e) {
    console.warn("压缩失败，使用原图", e);
    return file;
  }
}

/* ---------------------------------------------------------------- 识别 */
async function analyze() {
  if (!selectedFile) return;

  els.analyzeBtn.disabled = true;
  showLoading(true, "正在上传并压缩图片…");

  try {
    const file = await compress(selectedFile);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("provider", els.providerSelect.value);
    fd.append("annotate", els.annotateToggle.checked ? "true" : "false");

    showLoading(true, "大模型推理中，通常 2-6 秒…");

    const resp = await fetch("/api/analyze", { method: "POST", body: fd });
    const data = await resp.json().catch(() => ({}));

    if (!resp.ok) {
      throw new Error(data.detail || `请求失败（HTTP ${resp.status}）`);
    }

    if (data.status === "invalid_output") {
      showLoading(false);
      toast("模型输出不符合要求，请重试");
      renderError(data);
      return;
    }

    renderResult(data);
    loadHistory();
  } catch (err) {
    showLoading(false);
    toast(err.message || "识别失败，请检查网络或服务端日志");
    console.error(err);
  } finally {
    showLoading(false);
    els.analyzeBtn.disabled = false;
  }
}

els.analyzeBtn.addEventListener("click", analyze);

/* ---------------------------------------------------------------- 渲染 */
function renderResult(d) {
  const level = d.risk_level || "non_hallway";
  const color = d.risk_color || COLORS[level] || "#7a8699";

  els.resultCard.hidden = false;
  els.riskLevel.textContent = d.risk_level_cn || LIBELS[level] || level;
  els.riskLevel.style.color = color;
  els.riskScore.textContent = d.risk_score ?? "--";

  els.meterFill.style.width = `${Math.max(0, Math.min(100, d.risk_score ?? 0))}%`;
  els.meterFill.style.background = color;

  els.reviewTip.hidden = !d.need_review;

  els.metaHallway.textContent = d.is_hallway ? "是" : "否";
  els.metaHazards.textContent =
    d.hazards && d.hazards.length ? d.hazards.join("、") : "未发现";
  els.metaModel.textContent = `${d.provider} / ${d.model} · ${d.latency_ms}ms`;

  els.obsList.innerHTML = "";
  (d.observations || []).forEach((o) => {
    const li = document.createElement("li");
    li.textContent = o;
    els.obsList.appendChild(li);
  });
  if (!d.observations || !d.observations.length) {
    els.obsList.innerHTML = "<li>（模型未给出观察内容）</li>";
  }

  els.reasonText.textContent = d.reason || "（无）";

  els.adviceList.innerHTML = "";
  (d.advice || []).forEach((a) => {
    const li = document.createElement("li");
    li.textContent = a;
    els.adviceList.appendChild(li);
  });
  els.adviceBlock.hidden = !(d.advice && d.advice.length);

  // 标注图优先展示
  if (d.annotated_url) {
    els.previewImg.src = d.annotated_url;
  } else if (d.image_url) {
    els.previewImg.src = d.image_url;
  }

  els.resultCard.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderError(d) {
  els.resultCard.hidden = false;
  els.riskLevel.textContent = "识别失败";
  els.riskLevel.style.color = "#7a8699";
  els.riskScore.textContent = "--";
  els.meterFill.style.width = "0%";
  els.reviewTip.hidden = true;
  els.metaHallway.textContent = "--";
  els.metaHazards.textContent = "--";
  els.metaModel.textContent = `${d.provider || "-"} / ${d.model || "-"}`;
  els.obsList.innerHTML = "";
  els.reasonText.textContent = d.message || "模型未返回可解析的结果";
  els.adviceBlock.hidden = true;
}

/* ---------------------------------------------------------------- 历史 */
async function loadHistory() {
  try {
    const resp = await fetch("/api/history?limit=8");
    const data = await resp.json();
    const items = data.items || [];

    els.historyList.innerHTML = "";
    if (!items.length) {
      els.historyList.innerHTML = '<p class="muted">暂无记录</p>';
      return;
    }

    items.forEach((it) => {
      const level = it.risk_level || "unknown";
      const color = COLORS[level] || "#7a8699";

      const row = document.createElement("div");
      row.className = "history-item";

      const img = document.createElement("img");
      img.src = it.image_url || "";
      img.alt = "";
      img.loading = "lazy";

      const body = document.createElement("div");
      body.className = "hi-body";

      const title = document.createElement("div");
      title.className = "hi-title";
      title.textContent = LIBELS[level] || level;

      const sub = document.createElement("div");
      sub.className = "hi-sub";
      sub.textContent = `${it.created_at.replace("T", " ")} · ${it.risk_score ?? "-"}分 · ${it.latency_ms}ms`;

      body.append(title, sub);

      const pill = document.createElement("span");
      pill.className = "pill";
      pill.style.color = color;
      pill.textContent = `${it.risk_score ?? "-"}`;

      row.append(img, body, pill);
      els.historyList.appendChild(row);
    });
  } catch (e) {
    console.warn("历史记录加载失败", e);
  }
}

els.refreshHistory.addEventListener("click", loadHistory);

/* ---------------------------------------------------------------- 初始化 */
async function init() {
  try {
    const resp = await fetch("/api/health");
    const h = await resp.json();

    const providers = Object.entries(h.providers || {}).filter(
      ([, v]) => v.configured
    );

    els.providerSelect.innerHTML = "";
    if (!providers.length) {
      els.providerBadge.textContent = "未配置 Key";
      els.providerBadge.style.color = "#d8342f";
      toast("请先在 .env 中配置 DEEPSEEK_API_KEY 或 DASHSCOPE_API_KEY");
      els.analyzeBtn.disabled = true;
      return;
    }

    providers.forEach(([name, v]) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = `${name} · ${v.model}`;
      if (name === h.default_provider) opt.selected = true;
      els.providerSelect.appendChild(opt);
    });

    els.providerBadge.textContent = h.default_provider;
  } catch (e) {
    els.providerBadge.textContent = "离线";
    console.warn(e);
  }

  loadHistory();
}

init();
