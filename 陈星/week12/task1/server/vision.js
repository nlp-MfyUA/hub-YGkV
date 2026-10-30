const { requestTimeoutMs } = require("./config");
const { HttpError } = require("./errors");
const { SYSTEM_PROMPT, USER_PROMPT } = require("./prompt");
const { formatDetections } = require("./normalize");

const readErrorMessage = async (response) => {
  try {
    const data = await response.json();
    return data?.error?.message || data?.message || "";
  } catch {
    return "";
  }
};

const upstreamError = (status, detail) => {
  if (status === 401 || status === 403) {
    return new HttpError("模型服务鉴权失败，请检查服务端 API Key 配置", 502);
  }
  if (status === 404) {
    return new HttpError("未找到模型服务接口，请检查 Base URL 与模型名称配置", 502);
  }
  if (status === 429) {
    return new HttpError("模型服务请求过于频繁或额度不足，请稍后重试", 502);
  }
  const suffix = detail ? `：${String(detail).slice(0, 200)}` : "";
  return new HttpError(`模型服务调用失败（${status}）${suffix}`, 502);
};

const analyzeWithProvider = async (provider, imageDataUrl, detections = null) => {
  if (!provider.apiKey) {
    throw new HttpError(
      `${provider.name} 未配置 API Key，请在服务端 .env 中设置后重启`,
      503
    );
  }

  const detectionContext = Array.isArray(detections)
    ? `\n\n本地 YOLO 检测结果（仅作辅助参考，可能存在漏检或误检，最终以画面为准）：${formatDetections(
        detections
      )}。注意：YOLO 无法直接识别纸箱、电瓶、飞线等类别，电动车可能被识别为摩托车或自行车，请结合画面内容判断。`
    : "";

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), requestTimeoutMs);

  try {
    const response = await fetch(`${provider.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${provider.apiKey}`,
      },
      body: JSON.stringify({
        model: provider.model,
        messages: [
          { role: "system", content: SYSTEM_PROMPT },
          {
            role: "user",
            content: [
              { type: "text", text: USER_PROMPT + detectionContext },
              { type: "image_url", image_url: { url: imageDataUrl } },
            ],
          },
        ],
        temperature: 0.1,
        max_tokens: 1600,
        stream: false,
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      const detail = await readErrorMessage(response);
      throw upstreamError(response.status, detail);
    }

    const data = await response.json();
    const content = data?.choices?.[0]?.message?.content;
    const text = Array.isArray(content)
      ? content.map((part) => part?.text || "").join("")
      : content;

    if (!text || !String(text).trim()) {
      throw new HttpError("模型未返回有效识别结果，请重试", 502);
    }

    return {
      text: String(text),
      usage: data?.usage || null,
    };
  } catch (error) {
    if (error instanceof HttpError) throw error;
    if (error.name === "AbortError") {
      throw new HttpError("模型响应超时，请稍后重试", 504);
    }
    throw new HttpError(`无法连接模型服务：${error.message}`, 502);
  } finally {
    clearTimeout(timer);
  }
};

module.exports = { analyzeWithProvider };
