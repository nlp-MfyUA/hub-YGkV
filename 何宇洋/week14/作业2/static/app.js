"use strict";

const byId = (id) => document.getElementById(id);
const fileInput = byId("pdf-files");
const uploadButton = byId("upload-button");
const uploadFeedback = byId("upload-feedback");
const chatFeed = byId("chat-feed");
const questionInput = byId("question");
const imageInput = byId("question-image");
const removeImage = byId("remove-image");
const chatFeedback = byId("chat-feedback");
const askButton = byId("ask-button");
const statusLabels = {
  pending: "待解析",
  processing: "解析中",
  completed: "解析完成",
  failed: "解析失败",
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function request(path, options) {
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) {
    throw new Error(typeof result.detail === "string" ? result.detail : "请求失败，请重试");
  }
  return result;
}

let documentSnapshot = "";
let refreshInFlight = null;
function refreshDocuments() {
  if (!refreshInFlight) {
    refreshInFlight = request("/api/documents", {cache: "no-store"}).then((documents) => {
      byId("documents-feedback").textContent = "";
      const snapshot = JSON.stringify(documents);
      if (snapshot === documentSnapshot) return;
      documentSnapshot = snapshot;
      byId("document-count").textContent = `${documents.length} 份`;
      const items = documents.map((doc) => {
        const item = element("li", null, "document");
        item.append(element("strong", doc.name, "document-title"));
        item.append(element("span", statusLabels[doc.status], `badge ${doc.status}`));
        if (doc.error) item.append(element("p", doc.error, "document-detail"));
        return item;
      });
      byId("document-list").replaceChildren(...items);
    }).catch(() => {
      byId("documents-feedback").textContent = "暂时无法刷新文档状态，正在重试。";
    }).finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

function showSelectedFiles() {
  const count = fileInput.files.length;
  byId("file-selection").textContent = count ? `已选择 ${count} 份 PDF` : "每批最多 10 份 · 每份 20 MiB";
  uploadButton.disabled = count === 0;
}

fileInput.addEventListener("change", showSelectedFiles);
byId("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const files = [...fileInput.files];
  if (files.length === 0) return;
  if (files.length > 10) {
    uploadFeedback.textContent = "每批最多上传 10 份 PDF。";
    return;
  }
  const form = new FormData();
  for (const file of files) form.append("files", file);
  uploadButton.disabled = true;
  fileInput.disabled = true;
  uploadFeedback.textContent = "正在上传…";
  try {
    const result = await request("/api/documents", {method: "POST", body: form});
    uploadFeedback.textContent = result.rejected.map(({name, error}) => `${name}：${error}`).join("；");
    fileInput.value = "";
    await refreshDocuments();
  } catch (error) {
    uploadFeedback.textContent = error.message;
  } finally {
    fileInput.disabled = false;
    showSelectedFiles();
  }
});

function showSelectedImage() {
  const file = imageInput.files[0];
  byId("image-selection").textContent = file ? file.name : "";
  removeImage.hidden = !file;
}

imageInput.addEventListener("change", showSelectedImage);
removeImage.addEventListener("click", () => {
  imageInput.value = "";
  showSelectedImage();
  imageInput.focus();
});

function showAnswer(message, {blocks, sources}) {
  message.replaceChildren(element("h3", "DeepSeek"));
  for (const block of blocks) {
    if (block.type === "text") {
      message.append(element("p", block.text));
    } else if (block.type === "image") {
      const figure = element("figure");
      const image = element("img");
      image.src = block.url;
      image.alt = block.caption;
      figure.append(image, element("figcaption", block.caption));
      message.append(figure);
    }
  }
  if (!sources.length) return;
  const details = element("details", null, "sources");
  details.append(element("summary", "检索来源"));
  const list = element("ul");
  for (const source of sources) {
    const item = element("li");
    const link = element("a", `[来源${source.number}] ${source.name} · 第 ${source.page} 页`);
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    item.append(link);
    list.append(item);
  }
  details.append(list);
  message.append(details);
}

function scrollToLatest() {
  chatFeed.scrollTop = chatFeed.scrollHeight;
}

byId("chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = questionInput.value.trim();
  const image = imageInput.files[0];
  if (!question || askButton.disabled) return;
  if (image && image.size > 8 * 1024 * 1024) {
    chatFeedback.textContent = "图片上限为 8 MiB。";
    return;
  }
  const form = new FormData();
  form.append("question", question);
  if (image) form.append("image", image);
  questionInput.disabled = imageInput.disabled = removeImage.disabled = askButton.disabled = true;
  chatFeedback.textContent = "";
  byId("empty-chat")?.remove();
  const user = element("article", null, "message user");
  user.append(element("h3", "你"), element("p", question));
  if (image) {
    const preview = element("img");
    const url = URL.createObjectURL(image);
    const release = () => URL.revokeObjectURL(url);
    preview.addEventListener("load", release, {once: true});
    preview.addEventListener("error", release, {once: true});
    preview.src = url;
    preview.alt = image.name;
    user.append(preview);
  }
  const message = element("article", "正在生成回答…", "message");
  chatFeed.append(user, message);
  scrollToLatest();
  try {
    const result = await request("/api/chat", {method: "POST", body: form});
    showAnswer(message, result);
    questionInput.value = "";
    imageInput.value = "";
    showSelectedImage();
  } catch (error) {
    user.remove();
    message.remove();
    chatFeedback.textContent = error.message;
  } finally {
    questionInput.disabled = imageInput.disabled = removeImage.disabled = askButton.disabled = false;
    questionInput.focus();
    scrollToLatest();
  }
});

refreshDocuments();
setInterval(refreshDocuments, 1200);
