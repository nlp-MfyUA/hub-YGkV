import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertIcon,
  ArrowRightIcon,
  CameraIcon,
  ImageIcon,
  RefreshIcon,
  ScanIcon,
  SparklesIcon,
  SwitchCameraIcon,
  UploadIcon,
} from "./icons";
import { captureVideoFrame, formatSize, prepareImageFile } from "../utils/image";
import { useYolo } from "../hooks/useYolo";
import {
  LIVE_DETECTION_INTERVAL,
  detectObjects,
  groupDetections,
  renderDetections,
} from "../utils/yolo";

const describeCameraError = (error) => {
  switch (error?.name) {
    case "NotAllowedError":
    case "PermissionDeniedError":
      return "未获得摄像头权限。请在浏览器地址栏或系统设置中允许访问摄像头，然后重试。";
    case "NotFoundError":
    case "DevicesNotFoundError":
      return "未检测到可用摄像头，请改用上传图片或调用系统相机。";
    case "NotReadableError":
    case "TrackStartError":
      return "摄像头可能被其他应用占用，请关闭占用摄像头的应用后重试。";
    case "SecurityError":
      return "当前页面不是 HTTPS 安全环境，手机浏览器已禁用实时摄像头。请使用下方“调用系统相机”，或通过 HTTPS 地址访问。";
    case "OverconstrainedError":
      return "当前设备不支持所选摄像头，请切换摄像头后重试。";
    case "TimeoutError":
      return "摄像头启动超时。请检查浏览器地址栏的摄像头权限，或改用上传图片。";
    default:
      return "无法启动摄像头，请检查浏览器权限或改用上传图片。";
  }
};

const CAMERA_START_TIMEOUT = 15000;

/* 让出两帧，确保模型初始化的重活已经结束，主线程空闲后再请求摄像头 */
const nextFrame = () =>
  new Promise((resolve) => {
    if (typeof requestAnimationFrame !== "function") {
      setTimeout(resolve, 0);
      return;
    }
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  });

const withTimeout = (promise, ms, message) =>
  new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      const error = new Error(message);
      error.name = "TimeoutError";
      reject(error);
    }, ms);

    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      }
    );
  });

/* 等视频真正拿到画面帧，避免快门可点时实际还没有画面 */
const waitForVideoReady = (video) =>
  new Promise((resolve) => {
    if (!video || video.readyState >= 2) {
      resolve();
      return;
    }

    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      cleanup();
      resolve();
    };
    const cleanup = () => {
      video.removeEventListener("loadedmetadata", finish);
      video.removeEventListener("canplay", finish);
      video.removeEventListener("playing", finish);
      video.removeEventListener("error", finish);
      clearTimeout(timer);
    };

    const timer = setTimeout(finish, 6000);
    video.addEventListener("loadedmetadata", finish);
    video.addEventListener("canplay", finish);
    video.addEventListener("playing", finish);
    video.addEventListener("error", finish);
  });

const waitForImage = (image) => {
  if (image.complete) {
    return image.naturalWidth > 0
      ? Promise.resolve()
      : Promise.reject(new Error("图片加载失败"));
  }

  return new Promise((resolve, reject) => {
    const cleanup = () => {
      image.removeEventListener("load", handleLoad);
      image.removeEventListener("error", handleError);
    };
    const handleLoad = () => {
      cleanup();
      if (image.naturalWidth > 0) resolve();
      else reject(new Error("图片加载失败"));
    };
    const handleError = () => {
      cleanup();
      reject(new Error("图片加载失败"));
    };

    image.addEventListener("load", handleLoad);
    image.addEventListener("error", handleError);
  });
};

const CapturePanel = ({
  mode,
  onModeChange,
  photo,
  onPhotoReady,
  onRemovePhoto,
  providers,
  provider,
  onAnalyze,
  onDetectionsChange,
  analyzing,
}) => {
  const [cameraState, setCameraState] = useState("idle");
  const [cameraError, setCameraError] = useState("");
  const [fileError, setFileError] = useState("");
  const [processing, setProcessing] = useState(false);
  const [facingMode, setFacingMode] = useState("environment");
  const [retryKey, setRetryKey] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [liveDetections, setLiveDetections] = useState([]);
  const [photoDetection, setPhotoDetection] = useState({
    status: "idle",
    items: [],
  });

  const videoRef = useRef(null);
  const photoRef = useRef(null);
  const overlayRef = useRef(null);
  const streamRef = useRef(null);
  const uploadRef = useRef(null);
  const systemCameraRef = useRef(null);
  const onDetectionsChangeRef = useRef(onDetectionsChange);
  const lastPhotoDetectionsRef = useRef([]);
  const lastPhotoMetaRef = useRef(null);

  const { session: yolo, status: yoloStatus, retry: retryYolo } = useYolo();

  useEffect(() => {
    onDetectionsChangeRef.current = onDetectionsChange;
  }, [onDetectionsChange]);

  const stopStream = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }, []);

  /* ------------------------------ 摄像头 ------------------------------ */
  /*
   * 启动顺序：先等 YOLO 加载结束（成功或失败），再请求摄像头。
   * 模型下载 + WASM 初始化会长时间占用主线程，如果同时调用 getUserMedia，
   * 权限弹窗和视频流回调会被阻塞，表现就是“打开摄像头后一直转圈”。
   */
  useEffect(() => {
    if (mode !== "camera" || photo) {
      stopStream();
      if (mode !== "camera") setCameraState("idle");
      return undefined;
    }

    if (yoloStatus.status === "loading") {
      stopStream();
      setCameraState("waiting");
      setCameraError("");
      return undefined;
    }

    let cancelled = false;

    const startCamera = async () => {
      stopStream();
      setCameraState("starting");
      setCameraError("");

      try {
        // 先让主线程喘口气，再弹出摄像头授权
        await nextFrame();
        if (cancelled) return;

        if (!navigator.mediaDevices?.getUserMedia) {
          setCameraState("error");
          setCameraError(
            "当前浏览器不支持实时摄像头，或页面未通过 HTTPS 访问。请使用“调用系统相机”，或切换到上传图片。"
          );
          return;
        }

        let stream;
        try {
          stream = await withTimeout(
            navigator.mediaDevices.getUserMedia({
              video: {
                facingMode: { ideal: facingMode },
                width: { ideal: 1920 },
                height: { ideal: 1080 },
              },
              audio: false,
            }),
            CAMERA_START_TIMEOUT,
            "摄像头启动超时"
          );
        } catch (error) {
          if (error.name === "OverconstrainedError") {
            stream = await withTimeout(
              navigator.mediaDevices.getUserMedia({
                video: true,
                audio: false,
              }),
              CAMERA_START_TIMEOUT,
              "摄像头启动超时"
            );
          } else {
            throw error;
          }
        }

        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        streamRef.current = stream;
        const video = videoRef.current;
        if (video) {
          video.srcObject = stream;
          video.play().catch(() => {
            // 部分浏览器需要用户交互后才能播放，忽略即可
          });
          await waitForVideoReady(video);
        }

        if (cancelled) {
          stopStream();
          return;
        }
        setCameraState("ready");
      } catch (error) {
        if (cancelled) return;
        setCameraState("error");
        setCameraError(describeCameraError(error));
      }
    };

    startCamera();

    return () => {
      cancelled = true;
      stopStream();
    };
  }, [mode, photo, facingMode, retryKey, yoloStatus.status, stopStream]);

  /* --------------------------- 照片 YOLO 检测 --------------------------- */
  useEffect(() => {
    setLiveDetections([]);
    setPhotoDetection({ status: "idle", items: [] });
    lastPhotoDetectionsRef.current = [];
    lastPhotoMetaRef.current = null;
    renderDetections(overlayRef.current, []);

    if (!photo) {
      onDetectionsChangeRef.current?.({ items: [], available: false });
      return undefined;
    }

    if (yoloStatus.status === "error") {
      setPhotoDetection({ status: "error", items: [] });
      onDetectionsChangeRef.current?.({ items: [], available: false });
      return undefined;
    }

    if (!yolo || yoloStatus.status !== "ready") {
      setPhotoDetection({ status: "waiting", items: [] });
      onDetectionsChangeRef.current?.({ items: [], available: false });
      return undefined;
    }

    let cancelled = false;
    setPhotoDetection({ status: "detecting", items: [] });
    onDetectionsChangeRef.current?.({ items: [], available: false });

    const run = async () => {
      try {
        const image = photoRef.current;
        if (!image) return;

        await waitForImage(image);
        if (cancelled) return;

        const detections = await detectObjects(image, yolo);
        if (cancelled) return;

        const items = groupDetections(detections);
        lastPhotoDetectionsRef.current = detections;
        lastPhotoMetaRef.current = {
          sourceWidth: image.naturalWidth,
          sourceHeight: image.naturalHeight,
          fit: "contain",
        };

        setPhotoDetection({ status: "done", items });
        onDetectionsChangeRef.current?.({ items, available: true });
        renderDetections(overlayRef.current, detections, lastPhotoMetaRef.current);
      } catch (error) {
        if (cancelled) return;
        console.warn("YOLO 图片检测失败：", error);
        setPhotoDetection({ status: "error", items: [] });
        onDetectionsChangeRef.current?.({ items: [], available: false });
      }
    };

    run();

    return () => {
      cancelled = true;
    };
  }, [photo, yolo, yoloStatus.status]);

  /* --------------------------- 摄像头实时检测 --------------------------- */
  useEffect(() => {
    if (
      mode !== "camera" ||
      photo ||
      !yolo ||
      yoloStatus.status !== "ready" ||
      cameraState !== "ready"
    ) {
      return undefined;
    }

    let stopped = false;
    let timer = null;
    let running = false;

    const tick = async () => {
      if (stopped) return;

      const video = videoRef.current;
      if (
        !document.hidden &&
        video &&
        video.readyState >= 2 &&
        video.videoWidth &&
        !running
      ) {
        running = true;
        try {
          const detections = await detectObjects(video, yolo);
          if (!stopped) {
            setLiveDetections(groupDetections(detections));
            renderDetections(overlayRef.current, detections, {
              sourceWidth: video.videoWidth,
              sourceHeight: video.videoHeight,
              fit: "cover",
            });
          }
        } catch (error) {
          if (!stopped) console.warn("YOLO 实时检测失败：", error);
        } finally {
          running = false;
        }
      }

      if (!stopped) timer = setTimeout(tick, LIVE_DETECTION_INTERVAL);
    };

    timer = setTimeout(tick, 300);

    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [mode, photo, yolo, yoloStatus.status, cameraState]);

  /* --------------------------- 窗口尺寸变化重绘 --------------------------- */
  useEffect(() => {
    const handleResize = () => {
      if (photo && lastPhotoMetaRef.current) {
        renderDetections(
          overlayRef.current,
          lastPhotoDetectionsRef.current,
          lastPhotoMetaRef.current
        );
      }
    };

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [photo]);

  const handleCapture = async () => {
    setFileError("");
    if (!videoRef.current || cameraState !== "ready") return;

    try {
      const blob = await captureVideoFrame(videoRef.current);
      const url = URL.createObjectURL(blob);
      onPhotoReady({ blob, url, source: "camera" });
      stopStream();
    } catch (error) {
      setFileError(error.message);
    }
  };

  const handleFile = async (file) => {
    if (!file) return;
    setFileError("");
    setProcessing(true);

    try {
      const blob = await prepareImageFile(file);
      const url = URL.createObjectURL(blob);
      onPhotoReady({ blob, url, source: "upload", name: file.name });
    } catch (error) {
      setFileError(error.message);
    } finally {
      setProcessing(false);
      if (uploadRef.current) uploadRef.current.value = "";
      if (systemCameraRef.current) systemCameraRef.current.value = "";
    }
  };

  const handleDrop = (event) => {
    event.preventDefault();
    setDragging(false);
    handleFile(event.dataTransfer?.files?.[0]);
  };

  const activeProvider = providers.find((item) => item.id === provider);
  const activeDetections = photo ? photoDetection.items : liveDetections;
  const totalCount = activeDetections.reduce(
    (sum, item) => sum + item.count,
    0
  );
  const waitingForYolo = Boolean(
    photo &&
      (yoloStatus.status === "loading" ||
        photoDetection.status === "waiting" ||
        photoDetection.status === "detecting")
  );
  const canAnalyze = Boolean(
    photo && !analyzing && activeProvider?.available && !waitingForYolo
  );

  const engineStatusText = (() => {
    if (yoloStatus.status === "loading") {
      return `加载中 ${Math.round(yoloStatus.progress || 0)}%`;
    }
    if (yoloStatus.status === "error") return "加载失败";
    if (photoDetection.status === "detecting") return "检测中…";
    if (photoDetection.status === "waiting") return "等待模型…";
    if (photo && totalCount > 0) return `识别到 ${totalCount} 个目标`;
    if (photo) return "检测完成";
    if (liveDetections.length > 0) return `${totalCount} 个目标`;
    return "实时运行";
  })();

  const renderDetectionContent = () => {
    if (yoloStatus.status === "error") {
      return (
        <p className="detection-error">
          <AlertIcon size={14} />
          本地检测模型加载失败，将仅使用 DeepSeek 研判。
          <button type="button" onClick={retryYolo}>
            重试加载
          </button>
        </p>
      );
    }

    if (yoloStatus.status === "loading") {
      return (
        <>
          <p className="detection-empty">
            {yoloStatus.text}，完成后将自动检测画面中的物体。
          </p>
          <div className="yolo-progress" aria-hidden="true">
            <span style={{ width: `${Math.max(2, yoloStatus.progress || 0)}%` }} />
          </div>
        </>
      );
    }

    if (waitingForYolo || photoDetection.status === "idle") {
      return <p className="detection-empty">正在识别画面中的物体…</p>;
    }

    if (activeDetections.length > 0) {
      return (
        <div className="detection-chips">
          {activeDetections.slice(0, 12).map((item) => (
            <span
              key={item.label}
              className={`detection-chip ${
                item.hazard ? "detection-chip--warn" : ""
              }`}
              title={`最高置信度 ${Math.round(item.maxScore * 100)}%`}
            >
              {item.labelZh}
              <b>×{item.count}</b>
            </span>
          ))}
        </div>
      );
    }

    if (photo && photoDetection.status === "error") {
      return (
        <p className="detection-error">
          <AlertIcon size={14} />
          照片检测失败，将仅使用 DeepSeek 研判。
        </p>
      );
    }

    if (photo) {
      return (
        <p className="detection-empty">
          未检测到明显物体，仍可由 DeepSeek 结合画面继续研判。
        </p>
      );
    }

    if (mode === "upload") {
      return <p className="detection-empty">选择图片后将自动进行 YOLO 检测。</p>;
    }

    return (
      <p className="detection-empty">
        将摄像头对准楼道，YOLO 会持续检测画面中的物体。
      </p>
    );
  };

  return (
    <section className="card capture-card">
      <div className="card-head">
        <div>
          <span className="eyebrow">第一步</span>
          <h2>采集现场照片</h2>
        </div>
        <div className="mode-tabs" role="tablist" aria-label="照片来源">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "camera"}
            className={mode === "camera" ? "active" : ""}
            onClick={() => onModeChange("camera")}
          >
            <CameraIcon size={16} />
            拍照识别
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "upload"}
            className={mode === "upload" ? "active" : ""}
            onClick={() => onModeChange("upload")}
          >
            <UploadIcon size={16} />
            上传图片
          </button>
        </div>
      </div>

      <div
        className={`camera-stage ${dragging ? "dragging" : ""}`}
        onDragOver={(event) => {
          if (mode !== "upload" || photo) return;
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          if (mode !== "upload" || photo) return;
          handleDrop(event);
        }}
      >
        {photo ? (
          <>
            <img
              ref={photoRef}
              className="photo-preview"
              src={photo.url}
              alt="待识别的现场照片"
            />
            <canvas ref={overlayRef} className="detection-canvas" />
            <span className="stage-chip stage-chip--ready">
              <span className="status-dot status-dot--green" />
              照片已就绪
            </span>
            <span className="stage-chip stage-chip--size">
              {formatSize(photo.blob?.size)}
            </span>
          </>
        ) : mode === "camera" ? (
          <>
            <video ref={videoRef} className="camera-video" muted playsInline autoPlay />
            <canvas ref={overlayRef} className="detection-canvas" />
            <span
              className={`yolo-hud ${
                yoloStatus.status === "ready"
                  ? "yolo-hud--ready"
                  : yoloStatus.status === "error"
                  ? "yolo-hud--error"
                  : ""
              }`}
            >
              <span className="yolo-pulse" />
              {yoloStatus.status === "ready"
                ? `YOLO 实时检测${totalCount ? ` · ${totalCount}` : ""}`
                : yoloStatus.status === "loading"
                ? `YOLO 加载中 ${Math.round(yoloStatus.progress || 0)}%`
                : "YOLO 未就绪"}
            </span>
            <span className="frame-corner frame-corner--tl" />
            <span className="frame-corner frame-corner--tr" />
            <span className="frame-corner frame-corner--bl" />
            <span className="frame-corner frame-corner--br" />
            <span className="camera-hint">
              <CameraIcon size={15} />
              请将楼道、楼梯间或电梯厅完整拍入画面
            </span>

            {cameraState === "waiting" && (
              <div className="stage-overlay">
                <span className="spinner" />
                <p>
                  正在加载本地检测模型，加载完成后会自动开启摄像头…
                  {yoloStatus.status === "loading" &&
                    ` ${Math.round(yoloStatus.progress || 0)}%`}
                </p>
                <div className="yolo-progress stage-overlay__progress" aria-hidden="true">
                  <span
                    style={{ width: `${Math.max(2, yoloStatus.progress || 0)}%` }}
                  />
                </div>
                <div className="overlay-actions">
                  <button
                    type="button"
                    onClick={() => systemCameraRef.current?.click()}
                  >
                    <CameraIcon size={15} />
                    先拍一张
                  </button>
                </div>
              </div>
            )}

            {cameraState === "starting" && (
              <div className="stage-overlay">
                <span className="spinner" />
                <p>正在启动摄像头…</p>
              </div>
            )}

            {cameraState === "error" && (
              <div className="stage-overlay stage-overlay--error">
                <AlertIcon size={30} />
                <p>{cameraError}</p>
                <div className="overlay-actions">
                  <button
                    type="button"
                    onClick={() => setRetryKey((value) => value + 1)}
                  >
                    <RefreshIcon size={15} />
                    重试
                  </button>
                  <button
                    type="button"
                    onClick={() => systemCameraRef.current?.click()}
                  >
                    <CameraIcon size={15} />
                    调用系统相机
                  </button>
                </div>
              </div>
            )}
          </>
        ) : (
          <button
            type="button"
            className="upload-zone"
            onClick={() => uploadRef.current?.click()}
            disabled={processing}
          >
            <span className="upload-icon">
              <ImageIcon size={30} />
            </span>
            <strong>{processing ? "正在处理图片…" : "点击选择或拖入现场照片"}</strong>
            <span>支持 JPG、PNG、WebP，图片会自动压缩</span>
          </button>
        )}
      </div>

      <input
        ref={uploadRef}
        type="file"
        accept="image/*"
        hidden
        onChange={(event) => handleFile(event.target.files?.[0])}
      />
      <input
        ref={systemCameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(event) => handleFile(event.target.files?.[0])}
      />

      <div className="detection-strip">
        <div className="detection-strip__top">
          <span className="detection-engine">
            <ScanIcon size={15} />
            YOLO 本地检测
          </span>
          <span
            className={`engine-status ${
              yoloStatus.status === "error"
                ? "engine-status--error"
                : yoloStatus.status === "ready"
                ? "engine-status--ready"
                : ""
            }`}
          >
            {engineStatusText}
          </span>
        </div>

        {renderDetectionContent()}

        <p className="detection-note">
          <ScanIcon size={12} />
          YOLO 定位物体
          <ArrowRightIcon size={12} />
          <SparklesIcon size={12} />
          DeepSeek 结合画面与检测结果研判风险
        </p>
      </div>

      {photo ? (
        <div className="photo-controls">
          <span className="photo-meta">
            {photo.source === "camera" ? "来自现场拍摄" : "来自本地图片"}
            {photo.name ? ` · ${photo.name}` : ""}
          </span>
          <button
            type="button"
            className="ghost-btn"
            onClick={onRemovePhoto}
            disabled={analyzing}
          >
            <RefreshIcon size={16} />
            {photo.source === "camera" ? "重新拍摄" : "重新选择"}
          </button>
        </div>
      ) : mode === "camera" ? (
        <div className="capture-controls">
          <button
            type="button"
            className="ghost-btn"
            onClick={() =>
              setFacingMode((value) =>
                value === "environment" ? "user" : "environment"
              )
            }
            disabled={cameraState !== "ready"}
          >
            <SwitchCameraIcon size={17} />
            切换摄像头
          </button>

          <button
            type="button"
            className="shutter"
            onClick={handleCapture}
            disabled={cameraState !== "ready"}
            aria-label="拍摄照片"
          >
            <span />
          </button>

          <button
            type="button"
            className="ghost-btn"
            onClick={() => systemCameraRef.current?.click()}
          >
            <CameraIcon size={17} />
            系统相机
          </button>
        </div>
      ) : null}

      {fileError && (
        <p className="inline-error">
          <AlertIcon size={16} />
          {fileError}
        </p>
      )}

      <div className="analyze-bar">
        <div className="provider-picker">
          <span className="analyze-bar__label">研判模型</span>
          <div
            className="model-badge"
            title={activeProvider?.model || "deepseek-flash"}
          >
            <span
              className={`status-dot ${
                activeProvider?.available
                  ? "status-dot--green"
                  : "status-dot--gray"
              }`}
            />
            <strong>{activeProvider?.name || "DeepSeek Flash"}</strong>
            {activeProvider?.model && (
              <span className="model-badge__id">{activeProvider.model}</span>
            )}
          </div>
        </div>

        <button
          type="button"
          className="primary-btn"
          onClick={onAnalyze}
          disabled={!canAnalyze}
        >
          {analyzing ? (
            <>
              <span className="btn-spinner" />
              正在研判…
            </>
          ) : waitingForYolo ? (
            <>
              <span className="btn-spinner" />
              本地检测中…
            </>
          ) : (
            <>
              <SparklesIcon size={19} />
              开始智能识别
              <ArrowRightIcon size={18} />
            </>
          )}
        </button>
      </div>

      {!activeProvider?.available && (
        <p className="config-hint">
          <AlertIcon size={15} />
          识别服务未就绪：请在后端 <code>.env</code> 中配置
          <code> DEEPSEEK_API_KEY </code>，然后重启服务。
        </p>
      )}
    </section>
  );
};

export default CapturePanel;
