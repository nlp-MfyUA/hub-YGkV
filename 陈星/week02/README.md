# 大模型应用平台（Streamlit + DeepSeek）

NLP 课程作业：作业1 为基于 Streamlit 的四页面大模型应用；作业2 为基于 LLM tool call 的情感分析智能体。

## 作业1：四页面应用

作业：本地安装 Streamlit，配置大模型，使用四个页面完成应用。

### 功能页面
1. **💬 智能对话** —— 基于 DeepSeek 的多轮流式对话，可选模型与温度。
2. **📚 知识库问答 (RAG)** —— 上传 `.txt/.md/.pdf` 文档，自动切分并建立 TF-IDF 索引，基于文档片段检索增强问答。
3. **📊 表格数据分析** —— 上传 CSV，预览/统计/分布图，并用自然语言向模型提问。
4. **⚙️ 设置** —— 填写并保存 DeepSeek API Key / Base URL / 模型名，支持连接测试。

## 作业2：情感分析智能体

- 核心代码：`sentiment_agent.py` —— 借助 LLM 的 **tool call** 能力，将文本情感结构化输出为 `{label, confidence, reason}`，支持单条与批量分析。
- 页面：`pages/5_情感分析.py`，提供文本输入与结果可视化。

## 运行步骤
```bash
# 1. 创建并激活虚拟环境（可选）
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate  # macOS/Linux

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API Key
#    方式 A：复制 .env.example 为 .env 并填入 key
#    方式 B：启动后在「设置」页面填写

# 4. 启动
streamlit run app.py
```
浏览器打开 http://localhost:8501 即可。

## 获取 API Key
前往 https://platform.deepseek.com 注册并创建 API Key，填入设置页或 `.env`。
