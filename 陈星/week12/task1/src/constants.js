export const RISK_META = {
  high: {
    label: "高风险",
    level: 4,
    color: "#dc2626",
    soft: "#fef2f2",
    border: "#fecaca",
    description: "存在电动车、电瓶、飞线充电等可能起火的元素",
  },
  medium: {
    label: "中风险",
    level: 3,
    color: "#ea580c",
    soft: "#fff7ed",
    border: "#fed7aa",
    description: "大量堆积物严重影响通行，或堆放大量可燃物",
  },
  low: {
    label: "低风险",
    level: 2,
    color: "#d97706",
    soft: "#fffbeb",
    border: "#fde68a",
    description: "存在楼道堆物现象，但数量少、影响较小",
  },
  none: {
    label: "无隐患",
    level: 1,
    color: "#16a34a",
    soft: "#f0fdf4",
    border: "#bbf7d0",
    description: "楼道干净整洁，无堆放物品",
  },
  not_hallway: {
    label: "非楼道",
    level: 0,
    color: "#64748b",
    soft: "#f8fafc",
    border: "#e2e8f0",
    description: "画面与楼道无关，无法进行楼道隐患判定",
  },
};

export const RISK_GUIDE = [
  {
    level: "high",
    title: "高风险",
    text: "楼道中出现电动车、电瓶、飞线充电等可能起火的元素。",
  },
  {
    level: "medium",
    title: "中风险",
    text: "楼道中存在大量堆积物严重影响通行，或堆放大量纸箱、木质家具等能造成火势蔓延的堵塞物。",
  },
  {
    level: "low",
    title: "低风险",
    text: "存在楼道堆物现象，但不严重，基本不影响通行。",
  },
  {
    level: "none",
    title: "无隐患",
    text: "楼道干净整洁，无堆放物品，通道畅通。",
  },
  {
    level: "not_hallway",
    title: "非楼道",
    text: "一些与楼道无关的图片，不参与楼道隐患判定。",
  },
];

export const FALLBACK_PROVIDERS = [
  { id: "deepseek", name: "DeepSeek Flash", model: "deepseek-flash", available: false },
];

export const ANALYSIS_STEPS = [
  "正在上传现场照片…",
  "多模态模型正在观察画面…",
  "正在判断堆积物与起火风险…",
  "正在生成处置建议…",
];

export const getRiskMeta = (level) => RISK_META[level] || RISK_META.not_hallway;
