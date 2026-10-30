export const download = (url, onProgress) => {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("GET", url, true);
    request.responseType = "arraybuffer";

    if (typeof onProgress === "function") {
      request.onprogress = (event) => {
        if (!event.lengthComputable || !event.total) return;
        onProgress((event.loaded / event.total) * 100);
      };
    }

    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        resolve(request.response);
      } else {
        reject(new Error(`模型下载失败（HTTP ${request.status}）`));
      }
    };

    request.onerror = () => reject(new Error("模型下载失败，请检查网络或模型文件"));
    request.send();
  });
};
