# 深度研究助手（最简闭环版）

输入一个研究主题，自动完成：**规划关键词 → Bocha 网页搜索 → LLM 总结正文 → LLM 判断是否补检（不足则换关键词再来一轮）→ LLM 生成带来源引用的 Markdown 研究报告**。

## 文件结构

```
llm.py        # 统一的 LLM 调用入口（chat / chat_json），所有模块通过它调 DeepSeek
search.py     # Bocha 网页搜索
research.py   # 研究循环编排（规划→检索→总结→评审→报告）
main.py       # 命令行入口
api.py        # 极简 FastAPI（POST 发起 + GET 轮询）
.env          # 密钥与参数配置
```

## 使用

```bash
pip install -r requirements.txt

# 方式一：命令行直接跑
python main.py "2026 年主流 Agent 框架对比"

# 方式二：API
uvicorn api:app --port 8000
curl -X POST http://127.0.0.1:8000/api/research -H 'Content-Type: application/json' -d '{"topic":"你的主题"}'
curl http://127.0.0.1:8000/api/research/<research_id>   # 轮询
```

报告输出到 `output/report_日期.md`（含正文、来源列表、研究过程记录）。
