import streamlit as st
import re
import io
from llm_client import chat, get_config

st.set_page_config(page_title="知识库问答", page_icon="📚")
st.title("📚 知识库问答 (RAG)")

if "rag" not in st.session_state:
    st.session_state.rag = None
if "qa" not in st.session_state:
    st.session_state.qa = []

uploaded = st.file_uploader("上传文档 (.txt / .md / .pdf)", type=["txt", "md", "pdf"])
top_k = st.slider("检索片段数 (top-k)", 1, 5, 3)

if uploaded:
    with st.spinner("正在解析文档并建立索引..."):
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity

            name = uploaded.name.lower()
            if name.endswith(".pdf"):
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(uploaded.getvalue()))
                text = "\n".join((p.extract_text() or "") for p in reader.pages)
            else:
                text = uploaded.getvalue().decode("utf-8", errors="ignore")

            text = re.sub(r"\s+", " ", text).strip()
            chunks = []
            size, overlap = 500, 80
            start = 0
            while start < len(text):
                chunks.append(text[start:start + size])
                start += size - overlap
            chunks = [c for c in chunks if c.strip()]

            # analyzer="char" + ngram 对中文按字/词切分，避免默认英文分词把整段当一个词
            vec = TfidfVectorizer(analyzer="char", ngram_range=(1, 2))
            matrix = vec.fit_transform(chunks)
            st.session_state.rag = (vec, matrix, chunks)
            st.success(f"索引建立完成，共切分 {len(chunks)} 个片段。")
        except Exception as e:
            st.error(f"处理文档失败：{e}")

for q_text, a_text in st.session_state.qa:
    with st.chat_message("user"):
        st.markdown(q_text)
    with st.chat_message("assistant"):
        st.markdown(a_text)

if st.session_state.rag:
    if q := st.chat_input("基于文档提问..."):
        cfg = get_config()
        if not cfg["api_key"]:
            st.error("请先在「设置」页面配置 DeepSeek API Key。")
            st.stop()

        vec, matrix, chunks = st.session_state.rag
        qv = vec.transform([q])
        sims = cosine_similarity(qv, matrix).flatten()
        idx = [i for i in sims.argsort()[::-1][:top_k] if sims[i] > 0]
        context = "\n\n".join(f"[片段{i+1}] {chunks[i]}" for i in idx)

        if not context:
            st.warning("未在文档中找到相关内容。")
            st.stop()

        messages = [
            {"role": "system", "content": "你是文档问答助手。请仅根据下方提供的文档片段回答用户问题，不要编造。若片段中无答案，请如实说明。"},
            {"role": "user", "content": f"文档片段：\n{context}\n\n问题：{q}"},
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
