const MAX_CAPTURE_DIMENSION = 1280;
const MAX_UPLOAD_DIMENSION = 1600;
const MAX_FILE_BYTES = 25 * 1024 * 1024;

const canvasToBlob = (canvas, quality = 0.9) =>
  new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new Error("图片处理失败，请重试"));
      },
      "image/jpeg",
      quality
    );
  });

const drawToCanvas = (source, sourceWidth, sourceHeight, maxDimension) => {
  const scale = Math.min(1, maxDimension / Math.max(sourceWidth, sourceHeight));
  const width = Math.max(1, Math.round(sourceWidth * scale));
  const height = Math.max(1, Math.round(sourceHeight * scale));

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;

  const context = canvas.getContext("2d");
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);
  context.drawImage(source, 0, 0, width, height);

  return canvas;
};

const loadImageElement = (blob) =>
  new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const image = new Image();

    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("图片读取失败，请使用 JPG、PNG 或 WebP 格式"));
    };
    image.src = url;
  });

export const captureVideoFrame = async (video) => {
  const width = video?.videoWidth;
  const height = video?.videoHeight;

  if (!width || !height) {
    throw new Error("摄像头画面尚未就绪，请稍后重试");
  }

  const canvas = drawToCanvas(video, width, height, MAX_CAPTURE_DIMENSION);
  return canvasToBlob(canvas, 0.9);
};

export const prepareImageFile = async (file) => {
  if (!file) throw new Error("请选择需要识别的图片");
  if (!file.type.startsWith("image/")) {
    throw new Error("仅支持图片文件，请选择 JPG、PNG 或 WebP 格式");
  }
  if (file.size > MAX_FILE_BYTES) {
    throw new Error("图片过大（超过 25MB），请选择更小的图片");
  }

  const image = await loadImageElement(file);
  const canvas = drawToCanvas(image, image.naturalWidth, image.naturalHeight, MAX_UPLOAD_DIMENSION);
  return canvasToBlob(canvas, 0.88);
};

export const formatSize = (bytes) => {
  if (!Number.isFinite(bytes) || bytes <= 0) return "";
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

const blobToDataUrl = (blob) =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("生成缩略图失败"));
    reader.readAsDataURL(blob);
  });

export const createThumbnail = async (blob, maxDimension = 520) => {
  const image = await loadImageElement(blob);
  const canvas = drawToCanvas(image, image.naturalWidth, image.naturalHeight, maxDimension);
  const thumbnail = await canvasToBlob(canvas, 0.74);
  return blobToDataUrl(thumbnail);
};

