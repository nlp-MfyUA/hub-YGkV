"use strict";
const $ = id => document.getElementById(id);
let mode = "demo", selectedFile = null, previewURL = null, busy = false;
let currentReport = null, stream = null, records = [], configuration = null;

function showError(message = "") { $("error").textContent = message; $("error").hidden = !message; }
function setBusy(value) {
  busy = value;
  ["cameraBtn", "uploadBtn", "fileInput", "cameraInput", "clearBtn", "preset", "autoAnalyze", "demoMode"].forEach(id => $(id).disabled = value);
  $("liveMode").disabled = value || !configuration?.paid_enabled || !configuration?.key_configured;
  $("analyzeBtn").disabled = value || !selectedFile;
  $("analyzeBtn").textContent = value ? "检测中…" : "开始检测 →";
}
function resetResult() {
  currentReport = null;
  $("result").hidden = true;
  $("resultEmpty").hidden = false;
  $("reportTag").textContent = "等待检测";
}
function selectMode(next) {
  if (busy) return;
  mode = next;
  $("demoMode").classList.toggle("selected", mode === "demo");
  $("liveMode").classList.toggle("selected", mode === "live");
  $("presetGroup").hidden = mode === "live";
  $("modeNote").textContent = mode === "demo" ? "固定示例用于演示流程，未分析上传图片，不产生模型费用。" : "使用 DeepSeek 视觉模型分析图片，按账号用量计费。";
  showError(); resetResult();
}
async function chooseFile(file) {
  if (busy || !file) return;
  showError();
  // 先清除旧图片和报告，防止错误文件与旧结果关联。
  clearPhoto();
  if (!file.size || file.size > 10 * 1024 * 1024) return showError("请选择非空且不超过 10 MB 的图片。");
  selectedFile = file;
  previewURL = URL.createObjectURL(file);
  $("preview").src = previewURL;
  $("preview").hidden = false; $("emptyPreview").hidden = true;
  $("previewLabel").hidden = false; $("clearBtn").hidden = false;
  $("fileInfo").textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`;
  $("analyzeBtn").disabled = false;
  if ($("autoAnalyze").checked) await analyze();
}
function clearPhoto() {
  if (busy) return;
  if (previewURL) URL.revokeObjectURL(previewURL);
  previewURL = null; selectedFile = null;
  $("preview").removeAttribute("src"); $("preview").hidden = true;
  $("previewLabel").hidden = true; $("emptyPreview").hidden = false;
  $("clearBtn").hidden = true; $("analyzeBtn").disabled = true;
  $("fileInput").value = ""; $("cameraInput").value = "";
  $("fileInfo").textContent = "建议拍清楼道全貌、地面和堆放物";
  resetResult();
}
function fillList(id, values) {
  $(id).replaceChildren(...values.map(value => { const li = document.createElement("li"); li.textContent = value; return li; }));
}
function renderReport(report) {
  currentReport = report;
  $("resultEmpty").hidden = true; $("result").hidden = false;
  $("reportTag").textContent = report.mode === "demo" ? "模拟结果" : "检测完成";
  $("riskBanner").className = `risk-banner ${report.risk || "review"}`;
  $("riskLabel").textContent = report.label;
  $("riskSymbol").textContent = report.risk === "none" ? "✓" : report.risk === "not_corridor" ? "—" : "!";
  $("demoWarning").hidden = report.mode !== "demo";
  $("resultModel").textContent = report.model;
  $("elapsed").textContent = `${(report.elapsed_ms / 1000).toFixed(2)} 秒`;
  $("description").textContent = report.observation.description;
  fillList("evidence", report.observation.evidence);
  fillList("suggestions", report.suggestions);
  $("uncertainty").textContent = report.observation.uncertainty ? `需留意：${report.observation.uncertainty}` : "";
  $("uncertainty").hidden = !report.observation.uncertainty;
}
async function analyze() {
  if (!selectedFile || busy) return;
  resetResult(); showError(); setBusy(true);
  $("resultEmpty").hidden = true; $("loading").hidden = false;
  $("reportTag").textContent = "正在检测";
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 100000);
  try {
    const form = new FormData();
    form.append("file", selectedFile); form.append("mode", mode); form.append("preset", $("preset").value);
    const response = await fetch("/api/analyze", {method: "POST", body: form, signal: controller.signal});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "请求无效，请检查图片与表单。");
    const report = {...data, filename: selectedFile.name, timestamp: new Date().toISOString()};
    renderReport(report);
    records.unshift(report); records = records.slice(0, 20); renderHistory();
  } catch (error) {
    resetResult(); $("reportTag").textContent = "检测失败";
    showError(error.name === "AbortError" ? "等待超时。请求可能已送达模型，请确认后手动重试。" : error.message || "识别失败，请检查后端连接。");
  } finally {
    clearTimeout(timer); $("loading").hidden = true; setBusy(false);
  }
}
function download(report) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], {type:"application/json;charset=utf-8"}));
  const link = document.createElement("a"); link.href = url; link.download = `巡检报告-${report.id}.json`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function renderHistory() {
  $("historyCount").textContent = records.length;
  $("historyEmpty").hidden = records.length > 0;
  $("clearHistory").disabled = records.length === 0;
  $("historyList").replaceChildren(...records.map(report => {
    const row = document.createElement("div"); row.className = "history-item";
    const info = document.createElement("div");
    const title = document.createElement("strong"); title.textContent = report.filename;
    const meta = document.createElement("small"); meta.textContent = `${new Date(report.timestamp).toLocaleString("zh-CN")} · ${report.mode === "demo" ? "模拟示例，未识别照片" : "真实识别"}`;
    info.append(title, meta);
    const badge = document.createElement("span"); badge.className = "history-badge"; badge.textContent = report.label;
    const save = document.createElement("button"); save.className = "text-button"; save.textContent = "下载 ↓"; save.onclick = () => download(report);
    row.append(info, badge, save); return row;
  }));
}
function stopCamera() {
  if (stream) stream.getTracks().forEach(track => track.stop());
  stream = null; $("video").srcObject = null;
}
async function openCamera() {
  if (busy) return;
  showError();
  // 手机上优先系统拍照控件，也适用于局域网 HTTP 访问。
  if (/Android|iPhone|iPad|iPod/i.test(navigator.userAgent) || !window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    $("cameraInput").click(); return;
  }
  $("cameraBtn").disabled = true;
  try {
    stream = await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:"environment"}},audio:false});
    $("video").srcObject = stream; $("cameraDialog").showModal();
    await $("video").play();
  } catch {
    stopCamera(); if ($("cameraDialog").open) $("cameraDialog").close();
    showError("无法打开摄像头，请检查相机权限，或使用上传图片功能。手机可直接使用系统拍照。");
  } finally { $("cameraBtn").disabled = busy; }
}
$("shutter").onclick = () => {
  const video = $("video");
  if (!video.videoWidth) return;
  const scale = Math.min(1, 1600 / Math.max(video.videoWidth, video.videoHeight));
  const canvas = document.createElement("canvas"); canvas.width = Math.round(video.videoWidth * scale); canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  canvas.toBlob(blob => {
    if (!blob) return showError("拍照失败，请重试。");
    $("cameraDialog").close(); stopCamera();
    chooseFile(new File([blob], `楼道拍照-${Date.now()}.jpg`, {type:"image/jpeg"}));
  }, "image/jpeg", 0.9);
};
$("closeCamera").onclick = () => $("cameraDialog").close();
$("cameraDialog").addEventListener("close", stopCamera);
window.addEventListener("pagehide", stopCamera);
$("cameraBtn").onclick = openCamera;
$("uploadBtn").onclick = () => $("fileInput").click();
$("dropzone").onclick = () => { if (!busy) $("fileInput").click(); };
$("dropzone").onkeydown = event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); if (!busy) $("fileInput").click(); } };
for (const id of ["fileInput", "cameraInput"]) $(id).onchange = event => chooseFile(event.target.files[0]);
$("dropzone").ondragover = event => { event.preventDefault(); if (!busy) $("dropzone").classList.add("dragover"); };
$("dropzone").ondragleave = () => $("dropzone").classList.remove("dragover");
$("dropzone").ondrop = event => { event.preventDefault(); $("dropzone").classList.remove("dragover"); chooseFile(event.dataTransfer.files[0]); };
$("clearBtn").onclick = clearPhoto;
$("analyzeBtn").onclick = analyze;
$("demoMode").onclick = () => selectMode("demo");
$("liveMode").onclick = () => selectMode("live");
$("preset").onchange = () => { resetResult(); if (selectedFile && $("autoAnalyze").checked) analyze(); };
$("exportBtn").onclick = () => { if (currentReport) download(currentReport); };
$("clearHistory").onclick = () => { records = []; renderHistory(); };
fetch("/api/config").then(response => { if (!response.ok) throw new Error(); return response.json(); }).then(data => {
  configuration = data; setBusy(false); selectMode("demo");
  if (!data.paid_enabled) $("liveMode").title = "请在后端设置 ALLOW_PAID_API=1 并重启";
  else if (!data.key_configured) $("liveMode").title = "请在后端设置 DEEPSEEK_API_KEY 并重启";
}).catch(() => { $("modeNote").textContent = "后端连接失败"; showError("无法连接后端，请按 README 启动服务后刷新。"); });
