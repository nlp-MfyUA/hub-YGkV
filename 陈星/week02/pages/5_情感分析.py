"""作业2 的 Streamlit 页面：情感分析智能体。"""
import streamlit as st

from llm_client import get_config
from sentiment_agent import analyze_sentiment

st.set_page_config(page_title="情感分析", page_icon="😊")
st.title("😊 情感分析智能体")
st.caption("基于 LLM tool call 对文本进行情感极性判定（作业 2）")

text = st.text_area(
    "输入文本",
    value="这家店的服务态度真好，下次还来！",
    height=120,
    placeholder="输入一段需要分析情感的文本……",
)

if st.button("🔍 分析情感", type="primary"):
    if not get_config()["api_key"]:
        st.error("请先在「设置」页面配置 DeepSeek API Key。")
        st.stop()
    with st.spinner("正在调用大模型分析..."):
        try:
            r = analyze_sentiment(text)
        except Exception as e:  # 网络/密钥问题兜底，不让页面崩
            st.error(f"调用失败：{e}")
            r = None

    if r:
        emoji = {"正面": "🟢", "负面": "🔴", "中性": "⚪"}.get(r["label"], "⚪")
        st.success(f"{emoji} **{r['label']}**　置信度：{r['confidence']:.2f}")
        st.write("**理由：**", r["reason"])
