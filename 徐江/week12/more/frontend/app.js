/* 楼道消防风险识别 — 前端逻辑（原生 JS，无第三方依赖）
 *
 * 状态机（功能设计文档 §2）：
 *   idle → requesting_camera → previewing → captured → uploading → rendering → done
 *                ↓                ↓            ↓
 *            camera_denied    (可重拍)      upload_error → 可重试
 */
(function () {
  'use strict';

  // ---------- 常量 ----------
  var LEVEL_COLORS = {
    '高风险': '#D93025',
    '中风险': '#F29900',
    '低风险': '#1A73E8',
    '无风险': '#188038',
    '非楼道': '#5F6368'
  };
  var CONFIDENCE_LABEL = { high: '置信度高', medium: '置信度中', low: '置信度低' };
  var SCENE_LABEL = {
    stairwell: '楼梯间 / 疏散走道 / 安全出口',
    corridor: '公共走廊 / 电梯厅',
    elevator: '电梯轿厢',
    garage_passage: '地下车库通道',
    non_corridor: '非楼道场景'
  };
  var LEGAL_HINTS = {
    '高风险': '楼道内停放电动车或飞线充电违反消防规定，请立即清理并报告物业。',
    '中风险': '楼道堆放可燃杂物且影响通行，存在火势蔓延与疏散受阻风险，请尽快清理。',
    '低风险': '楼道存在少量堆物，建议保持通道畅通。',
    '无风险': '当前楼道整洁，请继续保持。',
    '非楼道': '未识别到楼道场景，请对准楼梯间或公共走廊重新拍摄。'
  };
  // 错误码 → 前端文案（功能设计文档 §5）
  var ERROR_MESSAGES = {
    unsupported_image_type: '请上传 JPEG/PNG/WebP 格式的图片',
    image_too_large: '图片过大，请重拍',
    image_too_small: '图片过小，请重拍',
    model_timeout: '识别超时，请重试',
    model_upstream_error: '识别服务异常，请稍后重试',
    model_output_unparseable: '识别结果异常，请重试',
    invalid_enum: '识别结果异常，请重试',
    provider_not_configured: '服务未配置',
    unauthorized: '演示令牌校验失败'
  };
  var MAX_EDGE = 1600;      // 压缩后长边上限
  var JPEG_QUALITY = 0.85;
  var HINT_DELAY_MS = 15000;  // 15s 后提示仍在识别
  var ABORT_DELAY_MS = 45000; // 45s 前端主动中断

  // ---------- DOM ----------
  function $(id) { return document.getElementById(id); }
  var video = $('video'), snapshot = $('snapshot'), cameraHint = $('camera-hint');
  var actionsIdle = $('actions-idle'), actionsPreviewing = $('actions-previewing'), actionsCaptured = $('actions-captured');
  var btnCamera = $('btn-camera'), btnCapture = $('btn-capture'), btnUpload = $('btn-upload'), btnRetake = $('btn-retake');
  var fileInput = $('file-input'), compressInfo = $('compress-info');
  var stageResult = $('stage-result'), errorBar = $('error-bar'), errorText = $('error-text'), btnErrorRetry = $('btn-error-retry');
  var resultCard = $('result-card'), loadingBox = $('loading-box'), loadingText = $('loading-text');
  var levelBlock = $('level-block'), levelText = $('level-text'), confidenceBadge = $('confidence-badge');
  var sceneLine = $('scene-line'), evidenceText = $('evidence-text');
  var signalsList = $('signals-list'), signalsEmpty = $('signals-empty');
  var legalHint = $('legal-hint'), overrideNote = $('override-note'), rawJson = $('raw-json');
  var btnAgain = $('btn-again');

  // ---------- 状态 ----------
  var state = 'idle';
  var stream = null;
  var currentBlob = null;   // 待上传的压缩后 Blob
  var abortCtrl = null;
  var hintTimer = null, abortTimer = null;

  function setState(next) {
    state = next;
    var previewing = next === 'previewing';
    actionsIdle.hidden = previewing || next !== 'idle';
    actionsPreviewing.hidden = !previewing;
    actionsCaptured.hidden = next !== 'captured';
    if (next !== 'captured') { compressInfo.hidden = true; }
  }

  // ---------- F-01 摄像头 ----------
  function stopCamera() {
    if (stream) {
      stream.getTracks().forEach(function (t) { t.stop(); });
      stream = null;
    }
    video.srcObject = null;
  }

  async function startCamera() {
    setState('requesting_camera');
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.isSecureContext) {
      showCameraDenied();
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false
      });
      video.srcObject = stream;
      snapshot.hidden = true;
      video.hidden = false;
      cameraHint.hidden = true;
      setState('previewing');
    } catch (err) {
      showCameraDenied();
    }
  }

  function showCameraDenied() {
    stopCamera();
    cameraHint.hidden = false;
    video.hidden = true;
    setState('camera_denied');
    // 保留「从相册选择」入口：actions-idle 仍可见
    actionsIdle.hidden = false;
    btnCamera.textContent = '重试开启摄像头';
  }

  // 页面切后台时释放摄像头，回前台可重新申请
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden' && stream) {
      stopCamera();
      if (state === 'previewing') {
        setState('idle');
        btnCamera.textContent = '开启摄像头';
      }
    }
  });

  // ---------- F-02 / F-04 压缩管线 ----------
  // 输入 Blob（拍照产物或相册文件），输出长边 ≤1600 的 JPEG Blob
  async function compressToJpeg(source, sourceWidth, sourceHeight) {
    var scale = Math.min(1, MAX_EDGE / Math.max(sourceWidth, sourceHeight));
    var w = Math.max(1, Math.round(sourceWidth * scale));
    var h = Math.max(1, Math.round(sourceHeight * scale));
    var canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    var ctx = canvas.getContext('2d');
    ctx.drawImage(source, 0, 0, w, h);
    var blob = await new Promise(function (resolve) {
      canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY);
    });
    if (!blob) { throw new Error('图片压缩失败'); }
    return { blob: blob, width: w, height: h };
  }

  async function capturePhoto() {
    if (!stream || !video.videoWidth) { return; }
    var out = await compressToJpeg(video, video.videoWidth, video.videoHeight);
    currentBlob = out.blob;
    snapshot.src = URL.createObjectURL(out.blob);
    video.hidden = true;
    snapshot.hidden = false;
    compressInfo.textContent =
      '压缩 ' + video.videoWidth + 'x' + video.videoHeight + ' → ' + out.width + 'x' + out.height +
      '，' + fmtSize(currentBlob.size) + '（原始约 ' + fmtSize(Math.round(out.blob.size / JPEG_QUALITY)) + '）';
    compressInfo.hidden = false;
    stopCamera();
    setState('captured');
  }

  function fmtSize(bytes) {
    return bytes >= 1024 * 1024
      ? (bytes / 1024 / 1024).toFixed(2) + ' MB'
      : Math.round(bytes / 1024) + ' KB';
  }

  async function handleFile(file) {
    if (!file) { return; }
    try {
      var bitmap = await createImageBitmap(file);
      var out = await compressToJpeg(bitmap, bitmap.width, bitmap.height);
      bitmap.close && bitmap.close();
      currentBlob = out.blob;
      snapshot.src = URL.createObjectURL(out.blob);
      video.hidden = true;
      snapshot.hidden = false;
      compressInfo.textContent =
        '压缩 ' + file.name + ' ' + fmtSize(file.size) + ' → ' + out.width + 'x' + out.height +
        '，' + fmtSize(out.blob.size);
      compressInfo.hidden = false;
      stopCamera();
      setState('captured');
    } catch (err) {
      showError('unsupported_image_type');
    }
  }

  // ---------- F-03 上传 ----------
  async function upload() {
    if (!currentBlob) { return; }
    hideError();
    setState('uploading');
    resultCard.hidden = true;
    loadingBox.hidden = false;
    loadingText.textContent = '识别中…';

    var form = new FormData();
    form.append('image', currentBlob, 'capture-' + Date.now() + '.jpg');

    abortCtrl = new AbortController();
    hintTimer = setTimeout(function () {
      if (state === 'uploading') { loadingText.textContent = '仍在识别，请稍候…'; }
    }, HINT_DELAY_MS);
    abortTimer = setTimeout(function () {
      if (abortCtrl) { abortCtrl.abort(); }
    }, ABORT_DELAY_MS);

    try {
      var resp = await fetch('/api/analyze', { method: 'POST', body: form, signal: abortCtrl.signal });
      if (!resp.ok) {
        var errBody = {};
        try { errBody = await resp.json(); } catch (e) { /* 非 JSON 错误体 */ }
        setState('upload_error');
        showError(errBody.error_code || 'model_upstream_error', errBody.detail);
        return;
      }
      var data = await resp.json();
      setState('rendering');
      renderResult(data);
    } catch (err) {
      setState('upload_error');
      if (err && err.name === 'AbortError') {
        showError('model_timeout', '前端等待超时（45 秒），请重试');
      } else {
        showError('network', '网络异常，请检查连接后重试');
      }
    } finally {
      clearTimeout(hintTimer);
      clearTimeout(abortTimer);
      loadingBox.hidden = true;
    }
  }

  // ---------- 结果渲染 ----------
  function renderResult(data) {
    errorBar.hidden = true;
    loadingBox.hidden = true;

    var color = LEVEL_COLORS[data.risk_level] || '#5F6368';
    levelBlock.style.background = color;
    levelText.textContent = data.risk_level;

    confidenceBadge.textContent = CONFIDENCE_LABEL[data.confidence] || data.confidence;
    confidenceBadge.className = 'confidence ' + (data.confidence || 'low');

    sceneLine.textContent = '场景：' + (SCENE_LABEL[data.scene_type] || data.scene_type) +
      '（' + data.scene_type + '）';
    evidenceText.textContent = data.evidence || '（模型未给出判定依据）';

    signalsList.innerHTML = '';
    var signals = data.signals || [];
    signalsEmpty.hidden = signals.length > 0;
    signals.forEach(function (s) {
      var li = document.createElement('li');
      var head = document.createElement('div');
      head.className = 'signal-head';
      var type = document.createElement('span');
      type.textContent = s.type || '未命名信号';
      var level = document.createElement('span');
      level.className = 'signal-level';
      level.textContent = s.level || '';
      level.style.color = LEVEL_COLORS[s.level] || '#5F6368';
      head.appendChild(type);
      head.appendChild(level);
      var detail = document.createElement('div');
      detail.className = 'signal-detail';
      detail.textContent = s.detail || '';
      li.appendChild(head);
      li.appendChild(detail);
      signalsList.appendChild(li);
    });

    legalHint.textContent = LEGAL_HINTS[data.risk_level] || '';
    overrideNote.hidden = !data.arbiter_override;
    rawJson.textContent = JSON.stringify(data, null, 2);

    resultCard.hidden = false;
    setState('done');
  }

  function showError(code, customDetail) {
    var msg = customDetail || ERROR_MESSAGES[code] || '识别失败，请重试';
    errorText.textContent = msg;
    errorBar.hidden = false;
    loadingBox.hidden = true;
    resultCard.hidden = true;
    stageResult.hidden = false;
  }

  function hideError() { errorBar.hidden = true; }

  function resetToCapture() {
    hideError();
    resultCard.hidden = true;
    currentBlob = null;
    snapshot.hidden = true;
    setState('idle');
    stageResult.hidden = true;
  }

  // ---------- 事件绑定 ----------
  btnCamera.addEventListener('click', startCamera);
  btnCapture.addEventListener('click', capturePhoto);
  btnRetake.addEventListener('click', function () {
    currentBlob = null;
    snapshot.hidden = true;
    hideError();
    startCamera();
  });
  btnUpload.addEventListener('click', upload);
  btnErrorRetry.addEventListener('click', upload);
  btnAgain.addEventListener('click', resetToCapture);
  fileInput.addEventListener('change', function (e) {
    stageResult.hidden = false;
    handleFile(e.target.files && e.target.files[0]);
    fileInput.value = '';
  });

  // ---------- 通道徽标（GET /api/config） ----------
  fetch('/api/config')
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (cfg) {
      if (!cfg) { return; }
      var badge = $('channel-badge');
      badge.textContent = '通道：' + cfg.provider + ' · ' + cfg.model;
      badge.hidden = false;
    })
    .catch(function () { /* 徽标加载失败不影响主流程 */ });
})();
