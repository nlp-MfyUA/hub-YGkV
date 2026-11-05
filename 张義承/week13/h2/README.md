# Chinook SQL Agent · Web 前端

在浏览器里用自然语言查询 Chinook 音乐商店数据库。后端直接复用
`week13/h1/sql_agent_langgraph.py` 的 LangGraph 实现，没有复制一份逻辑。

## 运行

先配置 API Key，两种方式任选其一。

**方式 A：`.env` 文件（推荐，一次配置长期有效）**

```bash
cd "/Users/zhanglei/zl/vscode/ai-homework/hub-study/张義承/week13/h2"
cp .env.example .env
# 编辑 .env，把 sk-xxxxxxxx 换成你的 key
```

**方式 B：启动前 export**

```bash
export DEEPSEEK_API_KEY=sk-xxxxxxxx
```

然后启动：

```bash
cd "/Users/zhanglei/zl/vscode/ai-homework/hub-study/张義承/week13/h2"
python3 -m uvicorn app:app --port 8000
```

浏览器打开 <http://127.0.0.1:8000>。开发时加 `--reload` 可以改完代码自动重启。

> `.env` 只在服务启动时读取一次。改完 key 需要重启服务。
> 可以用 `GET /api/health` 确认 `api_key_set` 是否为 `true`。

## 目录结构

```
h2/
├── app.py              # FastAPI 后端：/api/meta、/api/query、/api/health
├── static/
│   └── index.html      # 前端页面（原生 HTML/CSS/JS，无构建步骤）
├── requirements.txt
└── README.md
```

后端通过 `sys.path` 引入上一级 `h1/sql_agent_langgraph.py`，数据库路径由那份代码
自行解析到 `week13/chinook.db`。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 前端页面 |
| GET | `/api/meta` | 能力提示、示例问题、欢迎语、当前模型 |
| POST | `/api/query` | `{"question": "..."}` → 答案 + SQL + 结果 |
| GET | `/api/health` | 数据库路径、模型名、API key 是否就绪 |

`/api/query` 返回示例：

```json
{
  "ok": true,
  "thread_id": "web-1a2b3c4d5e6f",
  "answer": "数据库中一共有 59 位客户。",
  "sql": "SELECT COUNT(*) FROM customers;",
  "tables": ["customers"],
  "columns": ["COUNT(*)"],
  "rows": [[59]],
  "row_count": 1,
  "truncated": false,
  "steps": ["parse_db", "select_tables", "generate_sql", "validate_sql",
            "execute_sql", "summarize"],
  "gave_up": false
}
```

`steps` 是实际经过的节点顺序，前端用它渲染执行链路；如果发生改写，会重复出现
`validate_sql` / `rewrite_sql`。

## 说明

- 每次提问使用独立的 `thread_id`，互不干扰；图本身只编译一次。
- 启动时会预热数据库解析和模型客户端，第一个请求不用再等初始化。
- SQL 校验失败时，图会自动走 `rewrite_sql` 回环，最多 3 次；仍失败则返回
  `gave_up: true` 和错误详情，不会抛 500。
- 返回给前端的结果最多 200 行，超出部分用 `truncated` 标记。
