const { HttpError } = require("./errors");

const RISK_LABELS = {
  none: "无隐患",
  low: "低风险",
  medium: "中风险",
  high: "高风险",
  not_hallway: "非楼道",
};

const RISK_ALIASES = {
  none: "none",
  norisk: "none",
  safe: "none",
  clean: "none",
  "无隐患": "none",
  "无风险": "none",
  "安全": "none",
  low: "low",
  "低风险": "low",
  "低": "low",
  "轻微": "low",
  medium: "medium",
  mid: "medium",
  moderate: "medium",
  "中风险": "medium",
  "中等风险": "medium",
  "中": "medium",
  high: "high",
  "高风险": "high",
  "高": "high",
  "严重": "high",
  "重大": "high",
  nothallway: "not_hallway",
  nonhallway: "not_hallway",
  other: "not_hallway",
  unrelated: "not_hallway",
  "非楼道": "not_hallway",
  "非楼道场景": "not_hallway",
  "与楼道无关": "not_hallway",
};

const SEVERITY_ALIASES = {
  high: "high",
  "高风险": "high",
  "高": "high",
  "严重": "high",
  medium: "medium",
  mid: "medium",
  "中风险": "medium",
  "中": "medium",
  "中等": "medium",
  low: "low",
  "低风险": "low",
  "低": "low",
  "轻微": "low",
};

const DEFAULT_SUGGESTIONS = {
  high: [
    "立即将电动车、电瓶移出楼道并停止飞线充电",
    "联系物业、社区网格员或消防部门到场处置",
    "如发现冒烟、焦糊味或明火，立即拨打 119",
  ],
  medium: [
    "尽快清理楼道堆积物，保持疏散通道畅通",
    "将纸箱、木质家具等可燃物移出公共区域",
    "提醒住户不得占用、堵塞消防通道",
  ],
  low: [
    "建议清理楼道内的少量堆物",
    "引导住户将私人物品收回室内",
    "定期开展楼道巡查，保持通道整洁",
  ],
  none: ["保持楼道整洁与通道畅通", "定期检查消防设施和疏散指示标志"],
  not_hallway: ["请重新拍摄楼道、楼梯间或电梯厅等公共区域照片"],
};

const toKey = (value) =>
  String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s_-]/g, "");

const normalizeLevel = (value) => RISK_ALIASES[toKey(value)] || null;

const normalizeSeverity = (value, fallback) =>
  SEVERITY_ALIASES[toKey(value)] || fallback;

const toBooleanOrNull = (value) => {
  if (typeof value === "boolean") return value;
  if (value === 1 || value === 0) return value === 1;
  if (typeof value !== "string") return null;

  const text = value.trim().toLowerCase();
  if (["true", "yes", "y", "1", "是", "有", "存在"].includes(text)) return true;
  if (["false", "no", "n", "0", "否", "无", "没有"].includes(text)) return false;
  return null;
};

const toStringList = (value, limit = 8) => {
  let list = value;

  if (typeof value === "string") {
    list = value.split(/\r?\n|[；;]/);
  }
  if (!Array.isArray(list)) return [];

  return list
    .map((item) => {
      if (typeof item === "string") return item.trim();
      if (item && typeof item === "object") {
        return String(item.text || item.description || item.title || "").trim();
      }
      return "";
    })
    .filter(Boolean)
    .slice(0, limit);
};

const normalizeHazards = (value, fallbackSeverity) => {
  if (!Array.isArray(value)) return [];

  return value
    .map((item, index) => {
      if (typeof item === "string") {
        return {
          title: item.trim() || `隐患 ${index + 1}`,
          severity: fallbackSeverity,
          description: "",
        };
      }
      if (!item || typeof item !== "object") return null;

      return {
        title: String(item.title || item.name || item.type || `隐患 ${index + 1}`).trim(),
        severity: normalizeSeverity(item.severity, fallbackSeverity),
        description: String(item.description || item.detail || "").trim(),
      };
    })
    .filter(Boolean)
    .slice(0, 8);
};

const extractJson = (text) => {
  const source = String(text || "").replace(/^\uFEFF/, "").trim();
  if (!source) throw new HttpError("模型没有返回内容，请重试", 502);

  const fenced = source.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidate = fenced ? fenced[1].trim() : source;

  const start = candidate.indexOf("{");
  const end = candidate.lastIndexOf("}");
  if (start === -1 || end === -1 || end <= start) {
    throw new HttpError("模型返回内容不是有效的 JSON，请重试", 502);
  }

  const body = candidate.slice(start, end + 1);
  const attempts = [body, body.replace(/,\s*([}\]])/g, "$1")];

  for (const attempt of attempts) {
    try {
      return JSON.parse(attempt);
    } catch {
      // try next repair strategy
    }
  }

  throw new HttpError("模型返回内容不是有效的 JSON，请重试", 502);
};

const parseDetections = (value) => {
  if (value === undefined || value === null || value === "") return null;

  let list = value;
  if (typeof value === "string") {
    try {
      list = JSON.parse(value);
    } catch {
      return null;
    }
  }
  if (!Array.isArray(list)) return null;

  return list
    .slice(0, 30)
    .map((item) => {
      const rawScore = Number(item?.maxScore ?? item?.probability ?? 0);
      const score = Number.isFinite(rawScore)
        ? Math.min(1, Math.max(0, rawScore > 1 ? rawScore / 100 : rawScore))
        : 0;
      const label = String(item?.label || "").slice(0, 40);
      const labelZh = String(item?.labelZh || label).slice(0, 40);
      const count = Number(item?.count);
      return {
        label,
        labelZh,
        count: Number.isFinite(count) ? Math.max(1, Math.min(99, Math.round(count))) : 1,
        maxScore: Number(score.toFixed(3)),
      };
    })
    .filter((item) => item.labelZh)
    .slice(0, 20);
};

const formatDetections = (detections) => {
  if (!Array.isArray(detections) || detections.length === 0) {
    return "本地 YOLO 未检测到明显物体。";
  }
  return detections
    .map(
      (item) =>
        `${item.labelZh}×${item.count}（最高置信度 ${Math.round(item.maxScore * 100)}%）`
    )
    .join("、");
};

const normalizeAnalysis = (raw) => {
  if (!raw || typeof raw !== "object") {
    throw new HttpError("模型返回结果格式异常，请重试", 502);
  }

  let level = normalizeLevel(raw.risk_level ?? raw.riskLevel ?? raw.level ?? raw.risk);
  const hallwayFlag = toBooleanOrNull(raw.is_hallway ?? raw.isHallway);

  if (hallwayFlag === false) level = "not_hallway";
  if (!level) {
    throw new HttpError("模型返回的风险等级无法识别，请重试", 502);
  }

  const isHallway = level === "not_hallway" ? false : hallwayFlag !== false;
  const riskLabel = RISK_LABELS[level];

  let confidence = Number(raw.confidence ?? raw.score);
  if (!Number.isFinite(confidence)) {
    confidence = null;
  } else {
    if (confidence > 1 && confidence <= 100) confidence /= 100;
    confidence = Math.min(1, Math.max(0, Number(confidence.toFixed(3))));
  }

  const hazards =
    level === "not_hallway" ? [] : normalizeHazards(raw.hazards, level);
  const evidence = toStringList(raw.evidence ?? raw.observations);
  const suggestions =
    toStringList(raw.suggestions ?? raw.advice) || [];

  let summary = String(raw.summary || raw.description || "").trim();
  if (!summary) {
    summary =
      level === "not_hallway"
        ? "画面与居民楼楼道无关，无法进行楼道隐患判定。"
        : `画面判定为${riskLabel}。`;
  }

  const sceneType = String(raw.scene_type || raw.sceneType || "").trim();

  return {
    scene_type: sceneType || (isHallway ? "楼道" : "其他"),
    is_hallway: isHallway,
    risk_level: level,
    risk_label: riskLabel,
    confidence,
    summary,
    passage_blocked:
      level === "not_hallway"
        ? null
        : toBooleanOrNull(raw.passage_blocked ?? raw.passageBlocked),
    combustibles_present:
      level === "not_hallway"
        ? null
        : toBooleanOrNull(raw.combustibles_present ?? raw.combustiblesPresent),
    charging_detected:
      level === "not_hallway"
        ? null
        : toBooleanOrNull(raw.charging_detected ?? raw.chargingDetected),
    hazards,
    evidence,
    suggestions: suggestions.length
      ? suggestions
      : DEFAULT_SUGGESTIONS[level] || DEFAULT_SUGGESTIONS.none,
  };
};

module.exports = {
  extractJson,
  normalizeAnalysis,
  parseDetections,
  formatDetections,
  RISK_LABELS,
};
