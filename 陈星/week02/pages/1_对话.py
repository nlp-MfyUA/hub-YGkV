import streamlit as st
from llm_client import chat, get_config

st.set_page_config(page_title="智能对话", page_icon="💬")
st.title("💬 智能对话")

with st.sidebar:
    st.header("对话设置")
    cfg = get_config()
    model = st.selectbox("模型", ["deepseek-chat", "deepseek-reasoner"], index=0)
    temperature = st.slider("温度 (temperature)", 0.0, 1.0, 0.7, 0.1)
    if st.button("🗑️ 清空对话"):
        st.session_state.messages = []
        st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

if prompt := st.chat_input("输入消息，回车发送..."):
    cfg = get_config()
    if not cfg["api_key"]:
        st.error("请先在「设置」页面配置 DeepSeek API Key。")
        st.stop()

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        try:
            stream = chat(
                [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages],
                model=model,
                stream=True,
                temperature=temperature,
            )
            full = ""
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    full += delta
                    placeholder.markdown(full + "▌")
            placeholder.markdown(full)
            st.session_state.messages.append({"role": "assistant", "content": full})
        except Exception as e:
            placeholder.error(f"调用失败：{e}")
