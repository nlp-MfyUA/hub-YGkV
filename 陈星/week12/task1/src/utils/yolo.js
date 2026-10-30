import { InferenceSession, Tensor } from "onnxruntime-web";
import labels from "./labels.json";
import { getLabelZh } from "./labelZh";
import { download } from "./download";

const MODEL_SIZE = 640;
const TOPK = 100;
const DEFAULT_SCORE_THRESHOLD = 0.35;
const DEFAULT_IOU_THRESHOLD = 0.45;

const yieldToMain = () => new Promise((resolve) => setTimeout(resolve, 0));

export const LIVE_DETECTION_INTERVAL = 1000;

const VEHICLE_LABELS = new Set(["motorcycle", "bicycle", "car", "truck", "bus"]);
const CLUTTER_LABELS = new Set([
  "backpack",
  "suitcase",
  "chair",
  "couch",
  "dining table",
  "bench",
  "potted plant",
  "bottle",
  "cup",
  "vase",
]);

const PALETTE = [
  "#38bdf8",
  "#22d3ee",
  "#a78bfa",
  "#f472b6",
  "#34d399",
  "#fbbf24",
  "#60a5fa",
  "#c084fc",
];

export const isHazardRelevant = (label) =>
  VEHICLE_LABELS.has(label) || CLUTTER_LABELS.has(label);

const colorFor = (label, labelId) => {
  if (label === "motorcycle" || label === "bicycle") return "#ef4444";
  if (VEHICLE_LABELS.has(label)) return "#fb923c";
  if (CLUTTER_LABELS.has(label)) return "#f59e0b";
  return PALETTE[labelId % PALETTE.length];
};

const hexToRgba = (hex, alpha) => {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!result) return `rgba(56, 189, 248, ${alpha})`;
  return `rgba(${parseInt(result[1], 16)}, ${parseInt(result[2], 16)}, ${parseInt(
    result[3],
    16
  )}, ${alpha})`;
};

/* ------------------------------ 模型加载状态 ------------------------------ */
let yoloPromise = null;
const listeners = new Set();
let yoloState = {
  status: "loading",
  text: "正在准备本地检测引擎…",
  progress: 0,
};

const setYoloState = (patch) => {
  yoloState = { ...yoloState, ...patch };
  listeners.forEach((listener) => {
    try {
      listener(yoloState);
    } catch {
      // ignore listener errors
    }
  });
};

export const subscribeYolo = (listener) => {
  listeners.add(listener);
  listener(yoloState);
  return () => listeners.delete(listener);
};

const initYolo = async () => {
  setYoloState({ status: "loading", text: "正在加载 YOLOv8 模型…", progress: 2 });
  await yieldToMain();

  const baseUrl = `${process.env.PUBLIC_URL || ""}/model`;
  const netBuffer = await download(`${baseUrl}/yolov8n.onnx`, (percent) => {
    setYoloState({
      status: "loading",
      text: "正在加载 YOLOv8 模型…",
      progress: Math.min(91, Math.round(3 + percent * 0.88)),
    });
  });

  const nmsBuffer = await download(`${baseUrl}/nms-yolov8.onnx`, (percent) => {
    setYoloState({
      status: "loading",
      text: "正在加载 NMS 模块…",
      progress: Math.min(95, Math.round(92 + percent * 0.03)),
    });
  });

  await yieldToMain();
  setYoloState({ status: "loading", text: "正在初始化推理引擎…", progress: 96 });
  const net = await InferenceSession.create(netBuffer, {
    executionProviders: ["wasm"],
  });
  const nms = await InferenceSession.create(nmsBuffer, {
    executionProviders: ["wasm"],
  });

  await yieldToMain();
  setYoloState({ status: "loading", text: "正在预热模型…", progress: 98 });
  const warmup = new Tensor(
    "float32",
    new Float32Array(1 * 3 * MODEL_SIZE * MODEL_SIZE),
    [1, 3, MODEL_SIZE, MODEL_SIZE]
  );
  await net.run({ images: warmup });
  warmup.dispose?.();

  // 让出一帧，等 React 把“已就绪”渲染完，再让摄像头去抢主线程
  await yieldToMain();
  setYoloState({ status: "ready", text: "YOLO 模型已就绪", progress: 100 });
  return { net, nms };
};

export const loadYolo = () => {
  if (yoloPromise) return yoloPromise;

  yoloPromise = initYolo().catch((error) => {
    yoloPromise = null;
    setYoloState({
      status: "error",
      text: error.message || "YOLO 模型加载失败",
      progress: 0,
    });
    throw error;
  });

  return yoloPromise;
};

export const reloadYolo = () => {
  yoloPromise = null;
  return loadYolo();
};

/* -------------------------------- 图像预处理 -------------------------------- */
const getSourceSize = (source) => {
  const width =
    source?.videoWidth || source?.naturalWidth || source?.width || 0;
  const height =
    source?.videoHeight || source?.naturalHeight || source?.height || 0;
  return [width, height];
};

const createInputTensor = (source, width, height) => {
  const canvas = document.createElement("canvas");
  canvas.width = MODEL_SIZE;
  canvas.height = MODEL_SIZE;

  const context = canvas.getContext("2d", { willReadFrequently: true });
  context.fillStyle = "rgb(114, 114, 114)";
  context.fillRect(0, 0, MODEL_SIZE, MODEL_SIZE);

  const scale = Math.min(MODEL_SIZE / width, MODEL_SIZE / height);
  const newWidth = Math.max(1, Math.round(width * scale));
  const newHeight = Math.max(1, Math.round(height * scale));
  const left = Math.floor((MODEL_SIZE - newWidth) / 2);
  const top = Math.floor((MODEL_SIZE - newHeight) / 2);

  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(
    source,
    0,
    0,
    width,
    height,
    left,
    top,
    newWidth,
    newHeight
  );

  const pixels = context.getImageData(0, 0, MODEL_SIZE, MODEL_SIZE).data;
  const planeSize = MODEL_SIZE * MODEL_SIZE;
  const input = new Float32Array(3 * planeSize);

  for (let index = 0; index < planeSize; index += 1) {
    const offset = index * 4;
    input[index] = pixels[offset] / 255;
    input[planeSize + index] = pixels[offset + 1] / 255;
    input[2 * planeSize + index] = pixels[offset + 2] / 255;
  }

  return {
    tensor: new Tensor("float32", input, [1, 3, MODEL_SIZE, MODEL_SIZE]),
    newWidth,
    newHeight,
    left,
    top,
  };
};

/* -------------------------------- 目标检测 -------------------------------- */
export const detectObjects = async (source, session, options = {}) => {
  if (!session?.net || !session?.nms) return [];

  const [width, height] = getSourceSize(source);
  if (!width || !height) return [];

  const {
    scoreThreshold = DEFAULT_SCORE_THRESHOLD,
    iouThreshold = DEFAULT_IOU_THRESHOLD,
    topk = TOPK,
  } = options;

  const { tensor, newWidth, newHeight, left, top } = createInputTensor(
    source,
    width,
    height
  );
  const config = new Tensor(
    "float32",
    new Float32Array([topk, iouThreshold, scoreThreshold])
  );

  try {
    const { output0 } = await session.net.run({ images: tensor });
    const { selected } = await session.nms.run({
      detection: output0,
      config,
    });

    const count = selected.dims[1] || 0;
    const stride = selected.dims[2] || 6;
    const data = selected.data;
    const detections = [];

    for (let index = 0; index < count; index += 1) {
      const offset = index * stride;
      const centerX = data[offset];
      const centerY = data[offset + 1];
      const boxWidth = data[offset + 2];
      const boxHeight = data[offset + 3];

      let probability = 0;
      let labelId = 0;
      for (let classIndex = 4; classIndex < stride; classIndex += 1) {
        if (data[offset + classIndex] > probability) {
          probability = data[offset + classIndex];
          labelId = classIndex - 4;
        }
      }

      if (probability < scoreThreshold || !labels[labelId]) continue;

      const x1 = Math.max(
        0,
        Math.min(1, (centerX - boxWidth / 2 - left) / newWidth)
      );
      const y1 = Math.max(
        0,
        Math.min(1, (centerY - boxHeight / 2 - top) / newHeight)
      );
      const x2 = Math.max(
        0,
        Math.min(1, (centerX + boxWidth / 2 - left) / newWidth)
      );
      const y2 = Math.max(
        0,
        Math.min(1, (centerY + boxHeight / 2 - top) / newHeight)
      );

      if (x2 <= x1 || y2 <= y1) continue;

      const label = labels[labelId];
      detections.push({
        label,
        labelId,
        labelZh: getLabelZh(label),
        probability: Number(probability.toFixed(4)),
        box: [x1, y1, x2 - x1, y2 - y1],
      });
    }

    return detections.sort((a, b) => b.probability - a.probability);
  } finally {
    if (typeof tensor.dispose === "function") tensor.dispose();
    if (typeof config.dispose === "function") config.dispose();
  }
};

/* -------------------------------- 结果分组 -------------------------------- */
export const groupDetections = (detections = []) => {
  const map = new Map();

  detections.forEach((detection) => {
    const current = map.get(detection.label) || {
      label: detection.label,
      labelZh: detection.labelZh,
      count: 0,
      maxScore: 0,
    };
    current.count += 1;
    current.maxScore = Math.max(current.maxScore, detection.probability);
    map.set(detection.label, current);
  });

  return Array.from(map.values())
    .map((item) => ({
      ...item,
      maxScore: Number(item.maxScore.toFixed(3)),
      hazard: isHazardRelevant(item.label),
    }))
    .sort((a, b) => b.count - a.count || b.maxScore - a.maxScore);
};

/* -------------------------------- 绘制检测框 -------------------------------- */
export const renderDetections = (canvas, detections = [], options = {}) => {
  if (!canvas) return;

  const rect = canvas.getBoundingClientRect();
  if (rect.width < 2 || rect.height < 2) return;

  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const pixelWidth = Math.round(rect.width * dpr);
  const pixelHeight = Math.round(rect.height * dpr);

  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }

  const context = canvas.getContext("2d");
  context.setTransform(dpr, 0, 0, dpr, 0, 0);
  context.clearRect(0, 0, rect.width, rect.height);

  const { sourceWidth, sourceHeight, fit = "contain" } = options;
  if (!sourceWidth || !sourceHeight || detections.length === 0) return;

  const scale =
    fit === "cover"
      ? Math.max(rect.width / sourceWidth, rect.height / sourceHeight)
      : Math.min(rect.width / sourceWidth, rect.height / sourceHeight);

  const drawWidth = sourceWidth * scale;
  const drawHeight = sourceHeight * scale;
  const offsetX = (rect.width - drawWidth) / 2;
  const offsetY = (rect.height - drawHeight) / 2;

  context.save();
  context.beginPath();
  context.rect(0, 0, rect.width, rect.height);
  context.clip();

  detections.forEach((detection) => {
    const [nx, ny, nw, nh] = detection.box;
    const x = offsetX + nx * drawWidth;
    const y = offsetY + ny * drawHeight;
    const width = nw * drawWidth;
    const height = nh * drawHeight;
    const color = colorFor(detection.label, detection.labelId);

    context.fillStyle = hexToRgba(color, 0.14);
    context.fillRect(x, y, width, height);

    context.strokeStyle = color;
    context.lineWidth = 2;
    context.strokeRect(x, y, width, height);

    const text = `${detection.labelZh} ${Math.round(detection.probability * 100)}%`;
    context.font =
      '600 12px "PingFang SC", "Microsoft YaHei", -apple-system, sans-serif';
    const textWidth = context.measureText(text).width;
    const labelHeight = 20;
    const labelY = y >= labelHeight ? y - labelHeight : y;

    context.fillStyle = color;
    context.fillRect(x, labelY, textWidth + 14, labelHeight);
    context.fillStyle = "#ffffff";
    context.textBaseline = "middle";
    context.fillText(text, x + 7, labelY + labelHeight / 2 + 0.5);
  });

  context.restore();
};
