// JavaScript：处理照片、摄像头、后端请求与报告显示（不在浏览器保存 API Key）。
const el = id => document.getElementById(id);

let currentFile = null;
let currentPreviewURL = null;
let cameraStream = null;
let busy = false;
let models = {};

function inform(text) {
  el("feedback").textContent = text;
}

function canAnalyze() {
  const provider = el("provider").value;
  return Boolean(currentFile && models[provider]?.configured && !busy);
}

function updateAvailability() {
  const provider = el("provider").value;
  const configured = Boolean(models[provider]?.configured);
  el("config-hint").textContent = configured
    ? "模型密钥已配置，可上传照片进行真实 AI 识别。"
    : "该模型尚未配置 API Key。请编辑项目根目录 .env；你仍可查看下方示意报告。";
  el("analyze-button").disabled = !canAnalyze();
}

function restorePhoto() {
  el("video").hidden = true;
  el("preview").hidden = !currentFile;
  el("placeholder").hidden = Boolean(currentFile);
}

function stopCamera() {
  if (cameraStream) cameraStream.getTracks().forEach(track => track.stop());
  cameraStream = null;
  el("video").srcObject = null;
  el("camera-tools").hidden = true;
  restorePhoto();
}

function resetReport() {
  el("risk-level").textContent = "等待检测";
  el("risk-level").removeAttribute("data-level");
  el("result-origin").textContent = "AI + RULES";
  el("description").textContent = "照片已选好，点击「开始 AI 风险检测」。";
  el("evidence-list").replaceChildren();
  el("suggestion").textContent = "检测后显示对应的处理建议。";
}

function choosePhoto(file) {
  if (!file) return;
  if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
    inform("仅支持 JPG、PNG、WebP 格式，手机 HEIC 照片请先转换为 JPG。");
    return;
  }
  if (file.size === 0 || file.size > 8 * 1024 * 1024) {
    inform("图片不能为空，且不能超过 8 MB。");
    return;
  }
  stopCamera();
  currentFile = file;
  if (currentPreviewURL) URL.revokeObjectURL(currentPreviewURL);
  currentPreviewURL = URL.createObjectURL(file);
  el("preview").src = currentPreviewURL;
  el("preview").hidden = false;
  el("placeholder").hidden = true;
  el("photo-status").textContent = "已选择照片";
  resetReport();
  updateAvailability();
  inform("已准备好照片。");
}

el("pick-button").onclick = () => el("gallery-input").click();
el("native-button").onclick = () => el("native-input").click();
for (const input of ["gallery-input", "native-input"]) {
  el(input).onchange = event => {
    choosePhoto(event.target.files?.[0]);
    event.target.value = "";
  };
}

el("provider").onchange = updateAvailability;

el("camera-button").onclick = async () => {
  if (cameraStream) {
    stopCamera();
    inform("摄像头已关闭。");
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    inform("此网址不支持实时摄像头。手机可尝试「手机拍照」；实时取景需要 HTTPS 或 localhost。");
    return;
  }
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: "environment" } }
    });
    el("video").srcObject = cameraStream;
    el("video").hidden = false;
    el("preview").hidden = true;
    el("placeholder").hidden = true;
    el("camera-tools").hidden = false;
    await el("video").play();
    inform("摄像头已开启。对准楼道后点击「拍摄当前画面」。");
  } catch (error) {
    stopCamera();
    inform("摄像头无法开启，请检查权限或改用手机系统拍照。");
  }
};
el("stop-camera-button").onclick = () => {
  stopCamera();
  inform("摄像头已关闭。");
};

el("shutter-button").onclick = () => {
  const video = el("video");
  if (!cameraStream || !video.videoWidth || !video.videoHeight) {
    inform("摄像头画面还没有准备好，请稍后再拍。");
    return;
  }
  const canvas = document.createElement("canvas");
  const scale = Math.min(1, 1600 / Math.max(video.videoWidth, video.videoHeight));
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  canvas.toBlob(blob => {
    if (!blob) return inform("拍照失败，请重新尝试。");
    choosePhoto(new File([blob], "corridor-photo.jpg", { type: "image/jpeg" }));
  }, "image/jpeg", 0.86);
};

function renderReport(report) {
  const levels = ["高风险", "中等风险", "低风险", "无隐患", "非楼道"];
  if (!levels.includes(report.risk_level)) throw new Error("后端返回了未知风险等级");
  el("risk-level").textContent = report.risk_level;
  el("risk-level").dataset.level = report.risk_level;
  el("description").textContent = report.description || "未提供场景描述";
  el("suggestion").textContent = report.suggestion || "请进行人工复核。";
  el("result-origin").textContent = report.is_demo ? "示意数据 · 非 AI" : "AI 识别 + Python 分级";
  const list = el("evidence-list");
  list.replaceChildren();
  const evidence = Array.isArray(report.evidence) && report.evidence.length
    ? report.evidence : ["没有报告明确的可见隐患证据"];
  for (const item of evidence) {
    const node = document.createElement("li");
    node.textContent = String(item); // 不渲染来自模型的 HTML，防止脚本注入
    list.appendChild(node);
  }
}

el("analyze-button").onclick = async () => {
  if (!canAnalyze()) return;
  busy = true;
  updateAvailability();
  inform("正在调用视觉模型识别照片，请稍候…");
  el("risk-level").textContent = "识别中…";
  el("risk-level").removeAttribute("data-level");
  const form = new FormData();
  form.append("image", currentFile, currentFile.name || "corridor.jpg");
  form.append("provider", el("provider").value);

  try {
    const response = await fetch("/api/analyze", { method: "POST", body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "模型识别失败");
    renderReport(data);
    inform("识别完成。AI 对照片的判断可能出错，请结合现场情况复核。");
  } catch (error) {
    el("risk-level").textContent = "检测失败";
    el("description").textContent = "本次没有获得有效检测结果，请核对网络、密钥和服务设置。";
    inform(error.message || "未知错误");
  } finally {
    busy = false;
    updateAvailability();
  }
};

// 无需 API Key 的静态示意报告：用于演示“结果页面”，不冒充真实识别。
el("example-button").onclick = () => {
  renderReport({
    risk_level: "中等风险",
    description: "示意场景：假设楼道中堆放了大量纸箱，妨碍人员通过。",
    evidence: ["示意：多处纸箱堆积", "示意：影响通行"],
    suggestion: "请尽快清理大量可燃堆积物，保持疏散通道畅通。",
    is_demo: true,
  });
  inform("这是一份固定的示意报告，没有调用大模型，也不是对所上传照片的识别结果。");
};

async function loadStatus() {
  try {
    const response = await fetch("/api/status");
    if (!response.ok) throw new Error();
    const data = await response.json();
    models = Object.fromEntries(data.models.map(item => [item.id, item]));
  } catch {
    models = {};
    inform("无法获取模型状态，请检查 Python 服务是否已启动。");
  }
  updateAvailability();
}

window.addEventListener("pagehide", () => {
  stopCamera();
  if (currentPreviewURL) URL.revokeObjectURL(currentPreviewURL);
});
loadStatus();
