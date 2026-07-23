"""作业2 的 Streamlit 页面：人物关系图谱可视化。"""
import html
import math

import streamlit as st

from relationship_agent import extract_relationships

st.set_page_config(page_title="关系图谱", page_icon="🕸️")
st.title("🕸️ 人物关系图谱")
st.caption("基于 LLM tool call 抽取人物关系，并可视化成图谱（作业 2）")


def build_svg(triples, size=560):
    """把三元组渲染成环形布局的 SVG 关系图（无第三方依赖）。"""
    nodes = []
    for t in triples:
        if t["source"] not in nodes:
            nodes.append(t["source"])
        if t["target"] not in nodes:
            nodes.append(t["target"])
    n = len(nodes)
    if n == 0:
        return ""

    cx = cy = size / 2
    r = size / 2 - 70
    pos = {}
    for i, name in enumerate(nodes):
        ang = 2 * math.pi * i / n - math.pi / 2
        pos[name] = (cx + r * math.cos(ang), cy + r * math.sin(ang))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="{size}" height="{size}" style="max-width:100%">'
    ]
    # 边 + 关系标签
    for t in triples:
        x1, y1 = pos[t["source"]]
        x2, y2 = pos[t["target"]]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#4D148C" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{mx:.1f}" y="{my:.1f}" fill="#7030A0" font-size="14" '
            f'text-anchor="middle" dy="-4">{html.escape(t["relation"])}</text>'
        )
    # 节点
    for name in nodes:
        x, y = pos[name]
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="26" fill="#4D148C"/>')
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" fill="#fff" font-size="14" '
            f'text-anchor="middle" dominant-baseline="central">{html.escape(name)}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


text = st.text_area(
    "输入文本",
    value="小明喜欢小姚，但是小姚喜欢小王。",
    height=120,
    placeholder="例如：小明喜欢小姚，但是小姚喜欢小王。",
)

if st.button("🔍 抽取关系", type="primary"):
    with st.spinner("正在调用大模型分析..."):
        try:
            triples = extract_relationships(text)
        except Exception as e:  # 网络/密钥问题兜底，不让页面崩
            st.error(f"调用失败：{e}")
            triples = []

    if not triples:
        st.warning("没有抽取到人物关系，换个句子试试。")
    else:
        st.success(f"共抽取到 {len(triples)} 条关系")

        st.subheader("📋 关系列表")
        st.table(
            [
                {"主体": t["source"], "关系": t["relation"], "客体": t["target"]}
                for t in triples
            ]
        )

        st.subheader("🕸️ 关系图谱")
        st.markdown(build_svg(triples), unsafe_allow_html=True)
