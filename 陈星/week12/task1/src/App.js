import React, { useCallback, useEffect, useMemo, useState } from "react";
import CapturePanel from "./components/CapturePanel";
import ResultPanel from "./components/ResultPanel";
import RiskGuide from "./components/RiskGuide";
import HistoryPanel, { HistoryDetail } from "./components/HistoryPanel";
import { ShieldIcon, CameraIcon, UploadIcon, AlertIcon, ScanIcon } from "./components/icons";
import { FALLBACK_PROVIDERS } from "./constants";
import { analyzeImage, fetchConfig } from "./api";
import { createThumbnail } from "./utils/image";
import {
  MAX_HISTORY_ITEMS,
  clearHistoryStorage,
  loadHistory,
  persistHistory,
} from "./utils/history";
import "./style/App.css";

const App = () => {
  const [mode, setMode] = useState("camera");
  const [photo, setPhoto] = useState(null);
  const [providers, setProviders] = useState(FALLBACK_PROVIDERS);
  const [provider, setProvider] = useState("deepseek");
  const [configError, setConfigError] = useState("");
  const [analysis, setAnalysis] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState(() => loadHistory());
  const [activeHistory, setActiveHistory] = useState(null);
  const [detections, setDetections] = useState({ items: [], available: false });

  const loadConfig = useCallback(async () => {
    setConfigError("");
    try {
      const data = await fetchConfig();
      const list = Array.isArray(data.providers) && data.providers.length
        ? data.providers
        : FALLBACK_PROVIDERS;
      setProviders(list);

      const preferred =
        list.find((item) => item.id === data.defaultProvider && item.available) ||
        list.find((item) => item.available) ||
        list.find((item) => item.id === data.defaultProvider) ||
        list[0];
      setProvider(preferred?.id || "deepseek");
    } catch (loadError) {
      setConfigError(loadError.message || "无法连接识别服务");
    }
  }, []);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  useEffect(
    () => () => {
      if (photo?.url) URL.revokeObjectURL(photo.url);
    },
    [photo]
  );

  const activeProvider = useMemo(
    () => providers.find((item) => item.id === provider),
    [providers, provider]
  );

  const providerLabel = activeProvider
    ? `${activeProvider.name}${activeProvider.model ? `（${activeProvider.model}）` : ""}`
    : "";

  const handlePhotoReady = (nextPhoto) => {
    setPhoto(nextPhoto);
    setDetections({ items: [], available: false });
    setAnalysis(null);
    setError("");
  };

  const handleRemovePhoto = () => {
    if (analyzing) return;
    setPhoto(null);
    setDetections({ items: [], available: false });
    setAnalysis(null);
    setError("");
  };

  const handleDetectionsChange = useCallback((payload) => {
    setDetections(payload || { items: [], available: false });
  }, []);

  const handleAnalyze = async () => {
    if (!photo || analyzing || !activeProvider?.available) return;

    setAnalyzing(true);
    setAnalysis(null);
    setError("");

    try {
      const data = await analyzeImage({
        blob: photo.blob,
        provider,
        detections: detections.available ? detections.items : null,
      });
      setAnalysis(data);

      try {
        const thumbnail = await createThumbnail(photo.blob);
        const item = {
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          thumbnail,
          created_at: new Date().toISOString(),
          analyzed_at: data.analyzed_at,
          provider_name: data.provider_name,
          model: data.model,
          elapsed_ms: data.elapsed_ms,
          yolo_detections: data.yolo_detections || [],
          result: data.result,
        };

        setHistory((previous) => {
          const next = [item, ...previous].slice(0, MAX_HISTORY_ITEMS);
          return persistHistory(next);
        });
      } catch (thumbnailError) {
        console.warn("生成历史缩略图失败：", thumbnailError);
      }
    } catch (analyzeError) {
      setError(analyzeError.message || "识别失败，请稍后重试");
    } finally {
      setAnalyzing(false);
    }
  };

  const handleClearHistory = () => {
    if (!window.confirm("确定清空全部识别记录吗？此操作不可恢复。")) return;
    clearHistoryStorage();
    setHistory([]);
    setActiveHistory(null);
  };

  const handleCloseHistory = useCallback(() => setActiveHistory(null), []);

  return (
    <div className="App">
      <header className="hero">
        <div className="hero-glow hero-glow--one" />
        <div className="hero-glow hero-glow--two" />
        <div className="hero-inner">
          <div className="brand">
            <span className="brand-mark">
              <ShieldIcon size={26} />
            </span>
            <div className="brand-text">
              <strong>楼道消防隐患智能识别</strong>
              <span>AI Fire Safety Inspector</span>
            </div>
            <span className="brand-divider" />
            <span className="brand-note">
              <span className="status-dot status-dot--green" />
              YOLO + DeepSeek 在线研判
            </span>
          </div>

          <div className="hero-main">
            <span className="hero-badge">
              <ScanIcon size={15} />
              YOLO 实时检测 · DeepSeek 研判
            </span>
            <h1>
              一张照片，
              <span className="hero-title-line">
                看清楼道里的<em>消防隐患</em>
              </span>
            </h1>
            <p>
              拍摄楼道现场照片，YOLO 先定位画面中的物体，DeepSeek 再结合画面与检测结果，
              识别堆积物、可燃物与电动车充电等风险，输出隐患等级与处置建议。
            </p>
            <div className="hero-points">
              <span>
                <CameraIcon size={16} />
                实时拍照
              </span>
              <span>
                <UploadIcon size={16} />
                图片上传
              </span>
              <span>
                <ScanIcon size={16} />
                YOLO 实时检测
              </span>
              <span>
                <ShieldIcon size={16} />
                五级风险研判
              </span>
            </div>
          </div>
        </div>
      </header>

      <main className="main">
        {configError && (
          <div className="banner banner--error" role="alert">
            <AlertIcon size={18} />
            <div>
              <strong>无法连接识别服务</strong>
              <span>{configError}，请确认后端已启动（默认端口 3001）。</span>
            </div>
            <button type="button" onClick={loadConfig}>
              重新连接
            </button>
          </div>
        )}

        <div className="workspace">
          <CapturePanel
            mode={mode}
            onModeChange={setMode}
            photo={photo}
            onPhotoReady={handlePhotoReady}
            onRemovePhoto={handleRemovePhoto}
            providers={providers}
            provider={provider}
            onAnalyze={handleAnalyze}
            onDetectionsChange={handleDetectionsChange}
            analyzing={analyzing}
          />

          <ResultPanel
            analysis={analysis}
            analyzing={analyzing}
            error={error}
            providerLabel={providerLabel}
            onRetry={handleAnalyze}
          />
        </div>

        <HistoryPanel
          items={history}
          onOpen={setActiveHistory}
          onClear={handleClearHistory}
        />

        <RiskGuide />

        <footer className="site-footer">
          <p>
            <ShieldIcon size={15} />
            AI 识别结果仅供参考，不能替代专业消防检查。紧急火情请立即拨打 119。
          </p>
          <p>照片仅用于本次识别，服务端不会保存原始图片。</p>
        </footer>
      </main>

      {activeHistory && (
        <HistoryDetail item={activeHistory} onClose={handleCloseHistory} />
      )}
    </div>
  );
};

export default App;
