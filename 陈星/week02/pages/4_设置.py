import streamlit as st
from llm_client import get_config, save_config, chat

st.set_page_config(page_title="设置", page_icon="⚙️")
st.title("⚙️ 设置")

cfg = get_config()
key_set = bool(cfg["api_key"])

with st.form("settings_form"):
    # 出于安全，绝不把已保存的密钥回填到输入框
    api_key = st.text_input(
        "DeepSeek API Key",
        value="",
        type="password",
        placeholder="已配置，留空则保持原值" if key_set else "在此粘贴你的 DeepSeek API Key",
        help="密钥不会回显到页面，仅保存在本地 .env 文件。",
    )
    base_url = st.text_input("API Base URL", value=cfg["base_url"])
    model = st.text_input("模型名称", value=cfg["model"])
    submitted = st.form_submit_button("💾 保存配置")
    if submitted:
        # 用户没填新 Key 时，保留已保存的 Key
        new_key = api_key.strip() or cfg["api_key"]
        save_config(new_key, base_url.strip(), model.strip())
        st.success("已保存！配置写入本地 .env 文件。")

st.divider()
if st.button("🔌 测试连接"):
    if not get_config()["api_key"]:
        st.warning("请先填写并保存 API Key。")
    else:
        with st.spinner("正在测试..."):
            try:
                resp = chat([{"role": "user", "content": "你好，请只回复 OK"}], stream=False)
                st.success(f"连接成功！模型回复：{resp.choices[0].message.content}")
            except Exception as e:
                st.error(f"连接失败：{e}")

st.caption("API Key 由 DeepSeek 官方平台 https://platform.deepseek.com 获取，配置仅保存在本地 .env 文件。")
