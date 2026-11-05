# 语言检测与翻译

检测输入文本的语种，中文翻译为英文，其他语种翻译为中文。

使用 OpenAI Agents SDK（`openai-agents`）+ DeepSeek API。

## 配置

打开 `language_translator.py`，修改文件顶部的配置区：

```python
BASE_URL = "https://api.deepseek.com"   # DeepSeek 接口地址（一般不用改）
API_KEY = ""                             # 填你的 DeepSeek API Key
MODEL_NAME = "deepseek-chat"             # 模型名称
```

## 安装依赖

```bash
pip install -r requirements.txt
```

## 运行

```bash
python language_translator.py
```

输入文本后输出 JSON：

```json
{
  "query_input": "今天天气很好",
  "language": "中文",
  "result": "The weather is great today."
}
```

## 目录结构

```
作业/
├── language_translator.py   # 主程序
├── requirements.txt         # 依赖
└── README.md                # 说明
```
