(function () {
  "use strict";

  var form = document.getElementById("model-form");
  var baseInput = document.getElementById("base-url");
  var keyInput = document.getElementById("api-key");
  var modelInput = document.getElementById("model-name");
  var submit = document.getElementById("config-submit");
  var status = document.getElementById("config-status");
  var backLink = document.getElementById("back-link");

  function showStatus(message, error) {
    status.classList.remove("hidden");
    status.textContent = message;
    status.className = "config-status" + (error ? " error" : " ok");
  }

  async function loadConfig() {
    try {
      var response = await fetch("/api/model-config");
      if (!response.ok) return;
      var data = await response.json();
      if (data.base_url) baseInput.value = data.base_url;
      if (data.model_name) modelInput.value = data.model_name;
      if (data.configured) {
        backLink.classList.remove("hidden");
        showStatus("当前已有模型配置，可直接修改后重新保存。", false);
      }
    } catch (ignored) {}
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    submit.disabled = true;
    showStatus("正在保存…", false);
    try {
      var response = await fetch("/api/model-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: baseInput.value.trim(),
          api_key: keyInput.value.trim(),
          model_name: modelInput.value.trim()
        })
      });
      var data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "保存失败");
      }
      showStatus("保存成功，正在进入聊天…", false);
      window.setTimeout(function () {
        window.location.href = "/";
      }, 500);
    } catch (error) {
      showStatus(error && error.message ? error.message : String(error), true);
      submit.disabled = false;
    }
  });

  loadConfig();
})();
