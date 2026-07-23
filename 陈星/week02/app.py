import streamlit as st
from llm_client import get_config

st.set_page_config(page_title="大模型应用平台", page_icon="🤖", layout="wide")

st.title("🤖 大模型应用平台")
st.caption("基于 Streamlit + DeepSeek 构建的多功能大语言模型应用")

cfg = get_config()
if cfg["api_key"]:
    st.success(f"✅ 模型已配置：`{cfg['model']}` @ `{cfg['base_url']}`")
else:
    st.warning("⚠️ 尚未配置 API Key，请先前往 **设置** 页面填写 DeepSeek API Key。")

st.divider()
st.subheader("🧭 功能导航")
col1, col2 = st.columns(2)
with col1:
    st.page_link("pages/1_对话.py", label="💬 智能对话", icon="💬")
    st.page_link("pages/2_知识库.py", label="📚 知识库问答 (RAG)", icon="📚")
    st.page_link("pages/5_关系图谱.py", label="🕸️ 人物关系图谱", icon="🕸️")
with col2:
    st.page_link("pages/3_表格分析.py", label="📊 表格数据分析", icon="📊")
    st.page_link("pages/4_设置.py", label="⚙️ 设置", icon="⚙️")

st.divider()
st.markdown(
    "**使用说明**\n"
    "1. 在「设置」中填入 DeepSeek API Key（官网 https://platform.deepseek.com ）。\n"
    "2. 在「对话」中与模型自由聊天。\n"
    "3. 在「知识库」上传文档，基于文档内容提问。\n"
    "4. 在「表格分析」上传 CSV，用自然语言分析数据。"
)
