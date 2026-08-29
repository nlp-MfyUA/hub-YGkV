## 作业1

LangChain 并没有替代模型的 Function Call。LangChain 最终仍然会把工具信息转换成 OpenAI API 能够识别的格式，再调用模型的原生 Tool Calling 能力。

Agent 可以自动完成以下步骤，耗时受到工具选择 + 工具执行 + 大模型调用的影响。

模型判断是否调用工具
  ↓
执行工具
  ↓
把工具结果返回给模型
  ↓
模型继续推理
  ↓
生成最终答案或者再次调用工具


## 作业2

步骤 1 — 请求到达：外部客户端发送 HTTP POST 请求到 /v1/text-cls/{regex|tfidf|bert|gpt}。

步骤 2 — FastAPI 接收：FastAPI 根据 URL 路由匹配到 main.py 中对应的处理函数，同时把请求体 JSON 按 TextClassifyRequest 做 Pydantic 校验和类型转换（数据不合法会直接返回 422）。

步骤 3 — 初始化：处理函数记录 start_time，先构造一个空的 TextClassifyResponse（回填 request_id、request_text，其余字段置空）。

步骤 4 — 打日志：logger.info() 打印请求 ID 和请求文本，方便联调排查。

步骤 5 — 调用模型：try 块内调用对应的 model_for_xxx(req.request_text)，得到分类结果写入 response.classify_result，同时 error_msg = "ok"。

步骤 6 — 异常兜底：若模型抛异常，进入 except 块——清空 classify_result，并把 traceback.format_exc() 完整堆栈写入 error_msg（保证接口永不 500）。

步骤 7 — 计算耗时：classify_time = round(time.time() - start_time, 3)，精确到毫秒。

步骤 8 — 返回：函数返回 TextClassifyResponse，FastAPI 自动将其序列化为 JSON 响应给客户端。

```
   客户端发出 HTTP POST 请求
   ──► /v1/text-cls/{regex | tfidf | bert | gpt}
          │
          ▼
   ┌───────────────────────────────┐
   │ FastAPI 路由匹配               │
   │ 请求体 JSON 按 Pydantic 校验    │
   │ ──► 转换出 TextClassifyRequest │
   └───────────────────────────────┘
          │ 交给对应的处理函数
          ▼
   ┌───────────────────────────────┐
   │ main.py 处理函数              │
   │ ① 记 start_time              │
   │ ② 初始化 TextClassifyResponse│
   │ ③ logger 打印请求            │
   └───────────────────────────────┘
          │ try:
          ▼
   ┌───────────────────────────────┐
   │ 调用模型引擎                  │
   │ model_for_xxx(request_text)   │
   └───────────────────────────────┘
          │
          ├── 成功 ──► classify_result = 模型输出
          │            error_msg = "ok"
          │
          └── 异常 ──► classify_result = ""
                       error_msg = traceback 堆栈
          │
          ▼
   计算 classify_time = now - start_time
          │
          ▼
   ┌───────────────────────────────┐
   │ 返回 TextClassifyResponse     │
   │ FastAPI 序列化 JSON           │
   └───────────────────────────────┘
          │
          ▼
   客户端收到 HTTP 200 JSON 响应
  （request_id / request_text /
    classify_result / classify_time / error_msg）
```

```
  【正则】request_text
    ──► 对每个类别正则 findall 匹配
    ──► 命中一个→记一个类别；全部未命中→"Other"
    ──► 返回类别（可多标签）

  【TFIDF】request_text
    ──► jieba 分词
    ──► 过滤停用词
    ──► tfidf.transform 向量化
    ──► LinearSVC.predict
    ──► 返回类别

  【BERT】request_text
    ──► tokenizer 编码(max_len=30, pad/trunc)
    ──► 构造 NewsDataset → DataLoader(batch=16)
    ──► model.eval() + no_grad 前向推理
    ──► argmax(logits) 得到类别索引
    ──► 索引→CATEGORY_NAME 映射
    ──► 返回类别

  【大模型】request_text
    ──► tfidf.transform 向量化待识别文本
    ──► 与训练集向量做点积，取相似度 top-10
    ──► 拼接成 Few-shot 参考例子
    ──► 构造提示词(角色+类别+例子+文本)
    ──► 调用 qwen-plus API (temperature=0)
    ──► 提取 API 返回文本作为类别
```
