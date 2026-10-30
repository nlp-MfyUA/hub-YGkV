const parseJson = async (response) => {
  try {
    return await response.json();
  } catch {
    return null;
  }
};

export const fetchConfig = async () => {
  const response = await fetch("/api/config", {
    headers: { Accept: "application/json" },
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      data?.error ||
        `识别服务返回 HTTP ${response.status}，请确认后端已启动（默认端口 3001）`
    );
  }
  if (!data) {
    throw new Error("识别服务返回了无法解析的响应，请检查代理或端口配置");
  }
  return data;
};

export const analyzeImage = async ({ blob, provider, detections = null }) => {
  const formData = new FormData();
  formData.append("image", blob, `hallway-${Date.now()}.jpg`);
  if (provider) formData.append("provider", provider);
  if (Array.isArray(detections)) {
    formData.append("detections", JSON.stringify(detections));
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120000);

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });
    const data = await parseJson(response);

    if (!response.ok) {
      throw new Error(data?.error || `识别失败（${response.status}），请稍后重试`);
    }
    return data;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("识别超时，请检查网络后重试");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
};
