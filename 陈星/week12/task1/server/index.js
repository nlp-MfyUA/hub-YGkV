const express = require("express");
const multer = require("multer");
const cors = require("cors");
const fs = require("fs");
const path = require("path");

const config = require("./config");
const { HttpError } = require("./errors");
const { analyzeWithProvider } = require("./vision");
const { extractJson, normalizeAnalysis, parseDetections } = require("./normalize");

const app = express();
const buildDir = path.join(__dirname, "..", "build");
const indexFile = path.join(buildDir, "index.html");

app.disable("x-powered-by");
app.use(cors());
app.use(express.json({ limit: "1mb" }));

/* ------------------------------ 限流 ------------------------------ */
const buckets = new Map();
const WINDOW_MS = 60 * 1000;

const rateLimit = (req, res, next) => {
  const now = Date.now();
  const key = req.ip || req.socket.remoteAddress || "unknown";
  const recent = (buckets.get(key) || []).filter((time) => now - time < WINDOW_MS);

  if (recent.length >= config.rateLimitPerMinute) {
    return res.status(429).json({ error: "请求过于频繁，请稍后再试" });
  }

  recent.push(now);
  buckets.set(key, recent);
  if (buckets.size > 5000) buckets.clear();
  next();
};

/* ----------------------------- 图片上传 ----------------------------- */
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: config.maxImageMB * 1024 * 1024, files: 1 },
  fileFilter: (req, file, cb) => {
    if (!file.mimetype || !file.mimetype.startsWith("image/")) {
      return cb(new HttpError("仅支持上传图片文件（JPG、PNG、WebP 等）", 400));
    }
    cb(null, true);
  },
});

const publicProviders = () =>
  Object.values(config.providers).map((provider) => ({
    id: provider.id,
    name: provider.name,
    description: provider.description,
    model: provider.model,
    available: Boolean(provider.apiKey),
  }));

const pickDefaultProvider = () => {
  const preferred = config.providers[config.defaultProvider];
  if (preferred?.apiKey) return preferred.id;
  const available = Object.values(config.providers).find((provider) => provider.apiKey);
  return available?.id || config.defaultProvider;
};

/* ------------------------------ 接口 ------------------------------ */
app.get("/api/health", (req, res) => {
  res.json({
    ok: true,
    defaultProvider: pickDefaultProvider(),
    providers: publicProviders(),
  });
});

app.get("/api/config", (req, res) => {
  res.json({
    defaultProvider: pickDefaultProvider(),
    maxImageMB: config.maxImageMB,
    providers: publicProviders(),
  });
});

app.post(
  "/api/analyze",
  rateLimit,
  (req, res, next) => {
    upload.single("image")(req, res, (error) => {
      if (!error) return next();
      if (error.code === "LIMIT_FILE_SIZE") {
        return res
          .status(413)
          .json({ error: `图片大小不能超过 ${config.maxImageMB}MB，请压缩后重试` });
      }
      return res.status(error.status || 400).json({ error: error.message || "图片上传失败" });
    });
  },
  async (req, res, next) => {
    const startedAt = Date.now();

    try {
      if (!req.file) {
        throw new HttpError("请上传需要识别的图片", 400);
      }

      const providerId = String(req.body.provider || "").trim() || pickDefaultProvider();
      const provider = config.providers[providerId];
      if (!provider) {
        throw new HttpError("仅支持 DeepSeek 识别模型", 400);
      }
      if (!provider.apiKey) {
        throw new HttpError(
          `${provider.name} 未配置 API Key，请在服务端 .env 中设置后重启`,
          503
        );
      }

      const mime = req.file.mimetype || "image/jpeg";
      const imageDataUrl = `data:${mime};base64,${req.file.buffer.toString("base64")}`;
      const detections = parseDetections(req.body.detections);

      const { text, usage } = await analyzeWithProvider(
        provider,
        imageDataUrl,
        detections
      );
      const result = normalizeAnalysis(extractJson(text));
      const elapsed = Date.now() - startedAt;

      console.log(
        `[analyze] provider=${provider.id} model=${provider.model} size=${(
          req.file.size / 1024
        ).toFixed(0)}KB yolo=${detections ? detections.length : 0}类 level=${
          result.risk_level
        } elapsed=${elapsed}ms`
      );

      res.json({
        provider: provider.id,
        provider_name: provider.name,
        model: provider.model,
        elapsed_ms: elapsed,
        analyzed_at: new Date().toISOString(),
        yolo_detections: detections || [],
        usage,
        result,
      });
    } catch (error) {
      next(error);
    }
  }
);

/* --------------------------- 生产环境静态资源 --------------------------- */
if (fs.existsSync(indexFile)) {
  app.use(express.static(buildDir));
  app.use((req, res, next) => {
    if (req.method !== "GET" || req.path.startsWith("/api/")) return next();
    res.sendFile(indexFile);
  });
}

app.use((req, res) => {
  res.status(404).json({ error: "接口不存在" });
});

app.use((error, req, res, next) => {
  if (res.headersSent) return next(error);

  const status = error.status || 500;
  if (status >= 500) {
    console.error("[server]", error.message);
  }
  res.status(status).json({ error: error.message || "服务器内部错误" });
});

const server = app.listen(config.port, config.host, () => {
  const providers = publicProviders();
  console.log("");
  console.log("  楼道消防安全隐患识别服务已启动");
  console.log(`  本地地址  http://localhost:${config.port}`);
  console.log(
    `  可用模型  ${
      providers
        .filter((provider) => provider.available)
        .map((provider) => provider.name)
        .join("、") || "未配置（请检查 .env）"
    }`
  );
  console.log(`  静态页面  ${fs.existsSync(indexFile) ? "build/ 已加载" : "未构建（开发模式由 CRA 提供）"}`);
  console.log("");
});

server.on("error", (error) => {
  if (error.code === "EADDRINUSE") {
    console.error("");
    console.error(`  端口 ${config.port} 已被占用，后端没有启动成功。`);
    console.error(`  常见原因：CRA 开发服务器占用了 ${config.port}（3000 被占用时会自动顺延）。`);
    console.error("  处理方式：先停掉占用该端口的进程，再运行 npm run server；");
    console.error("  或检查是否同时开了多个 npm run dev / npm start。");
    console.error("");
    process.exit(1);
  }

  console.error("[server]", error.message);
  process.exit(1);
});
