require("dotenv").config();

const toInt = (value, fallback) => {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const provider = {
  id: "deepseek",
  name: "DeepSeek Flash",
  description: "深度求索多模态模型",
  apiKey: process.env.DEEPSEEK_API_KEY || "",
  baseUrl: (process.env.DEEPSEEK_BASE_URL || "https://api.deepseek.com").replace(/\/+$/, ""),
  model: process.env.DEEPSEEK_MODEL || "deepseek-flash",
};

module.exports = {
  port: toInt(process.env.SERVER_PORT, 3001),
  host: process.env.SERVER_HOST || "0.0.0.0",
  maxImageMB: toInt(process.env.MAX_IMAGE_MB, 10),
  requestTimeoutMs: toInt(process.env.REQUEST_TIMEOUT_MS, 90000),
  rateLimitPerMinute: toInt(process.env.RATE_LIMIT_PER_MINUTE, 30),
  providers: { [provider.id]: provider },
  defaultProvider: provider.id,
};
