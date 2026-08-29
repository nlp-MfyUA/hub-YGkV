import streamlit as st
import pandas as pd
from llm_client import chat, get_config

st.set_page_config(page_title="表格数据分析", page_icon="📊")
st.title("📊 表格数据分析")

if "df" not in st.session_state:
    st.session_state.df = None
if "qa" not in st.session_state:
    st.session_state.qa = []

uploaded = st.file_uploader("上传 CSV 文件", type=["csv"])
if uploaded:
    try:
        df = pd.read_csv(uploaded)
        st.session_state.df = df
    except Exception as e:
        st.error(f"读取失败：{e}")

df = st.session_state.df
if df is not None:
    st.subheader("数据预览")
    st.dataframe(df.head(10), use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.write("**字段与类型**")
        st.json({k: str(v) for k, v in df.dtypes.items()})
    with c2:
        st.write("**数值统计**")
        st.dataframe(df.describe(include="all"))

    numeric = df.select_dtypes(include="number").columns.tolist()
    if numeric:
        col = st.selectbox("选择列绘制分布柱状图", numeric)
        if col:
            st.bar_chart(df[col].value_counts().head(20))

    st.divider()
    st.subheader("用自然语言提问")
    for q_text, a_text in st.session_state.qa:
        with st.chat_message("user"):
            st.markdown(q_text)
        with st.chat_message("assistant"):
            st.markdown(a_text)

    q = st.chat_input("例如：哪一类销量最高？平均价格是多少？")
    if q:
        cfg = get_config()
        if not cfg["api_key"]:
            st.error("请先在「设置」页面配置 DeepSeek API Key。")
            st.stop()
        context = (
            f"字段与类型：{dict(df.dtypes.astype(str))}\n"
            f"前 5 行：\n{df.head(5).to_string()}\n"
            f"统计摘要：\n{df.describe(include='all').to_string()}"
        )
        messages = [
            {"role": "system", "content": "你是一名数据分析师，请用中文基于给定的 CSV 数据信息回答用户问题，给出明确结论，必要时给出计算依据。"},
            {"role": "user", "content": f"数据信息：\n{context}\n\n问题：{q}"},
        ]
        with st.chat_message("user"):
            st.markdown(q)
        with st.chat_message("assistant"):
            placeholder = st.empty()
            try:
                stream = chat(messages, stream=True)
                full = ""
                for chunk in stream:
                    d = chunk.choices[0].delta.content
                    if d:
                        full += d
                        placeholder.markdown(full + "▌")
                placeholder.markdown(full)
                st.session_state.qa.append((q, full))
            except Exception as e:
                placeholder.error(f"调用失败：{e}")
