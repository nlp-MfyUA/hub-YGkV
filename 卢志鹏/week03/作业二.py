作业二：阅读意图识别 01-intent-classify 代码，梳理源文件的作用，绘制从fastapi 接受请求到
到返回结果的流程，绘制流程图（手绘、自然语言表达）。

答：意图识别 01-intent-classify 代码的 FastAPI 一共有四个路由接口，分别对应4种不同的意图识别策略：
- `/v1/text-cls/regex`：正则匹配
- `/v1/text-cls/tfidf`：TF-IDF + 传统机器学习
- `/v1/text-cls/bert`：BERT 深度学习
- `/v1/text-cls/gpt`：LLM + few-shot

调用链1：正则匹配 — `POST /v1/text-cls/regex`
```
regex_classify(req: TextClassifyRequest)
│
├─ 1. 记录开始时间 time.time()
├─ 2. 初始化空的 TextClassifyResponse
├─ 3. logger.info() 记录请求日志
├─ 4. 调用 → model_for_regex(req.request_text)    ← 核心
│       │
│       ├── 输入类型判断：str / list / 其他(抛异常)
│       │
│       ├── [str 分支]
│       │   ├── 遍历预编译的正则字典 REGEX_RULE_COMPILED
│       │   │   └── 对每个类别用 re.findall() 匹配文本
│       │   ├── 命中 → 加入 classify_result
│       │   └── 全部未命中 → 返回 ["Other"]
│       │
│       └── [list 分支]
│           ├── 遍历列表中每条文本
│           ├── 对每条文本遍历所有类别正则匹配
│           └── 未命中 → 加入 "Other"
│
├─ 5. 成功 → error_msg = "ok"
│   异常 → error_msg = traceback 堆栈信息
└─ 6. 计算耗时 classify_time → 返回 Response
```

调用链 2：TF-IDF 传统机器学习 — `POST /v1/text-cls/tfidf`
```
tfidf_classify(req: TextClassifyRequest)
│
├─ 1. 记录开始时间
├─ 2. 初始化空的 TextClassifyResponse
├─ 3. logger.info() 记录请求
├─ 4. 调用 → model_for_tfidf(req.request_text)    ← 核心
│       │
│       ├── 输入类型判断：str / list / 其他(抛异常)
│       │
│       ├── [str 分支]
│       │   ├── jieba.lcut(request_text) → 中文分词
│       │   ├── 过滤停用词（百度停用词表 cn_stopwords）
│       │   ├── " ".join(...) → 拼接为空格分隔的字符串
│       │   ├── tfidf.transform([query_words]) → TF-IDF特征向量
│       │   └── model.predict(...) → 模型预测类别
│       │
│       └── [list 分支]
│           ├── 对每条文本分别 jieba 分词 + 过滤停用词
│           ├── tfidf.transform(query_words) → 批量特征向量
│           └── model.predict(...) → 批量预测
│
├─ 5. 成功/异常处理
└─ 6. 计算耗时 → 返回 Response
```

调用链 3：BERT 深度学习 — `POST /v1/text-cls/bert`

```
bert_classify(req: TextClassifyRequest)
│
├─ 1. 记录开始时间
├─ 2. 初始化空的 TextClassifyResponse
├─ 3. 调用 → model_for_bert(req.request_text)    ← 核心
│       │
│       ├── 输入类型判断：str → 转为 [str] / list / 其他(抛异常)
│       │
│       ├── Tokenizer 编码
│       │   └── tokenizer(list(request_text), truncation=True, padding=True, max_length=30)
│       │       → 将文本转为 input_ids + attention_mask，截断/填充到30个token
│       │
│       ├── 构建 Dataset + DataLoader
│       │   ├── NewsDataset(encodings, labels=[0,...]) → 自定义 Dataset（标签为占位0）
│       │   └── DataLoader(batch_size=16, shuffle=False) → 批处理迭代器
│       │
│       ├── 模型推理
│       │   ├── model.eval() → 切换到评估模式（关闭 Dropout 等）
│       │   ├── 遍历每个 batch:
│       │   │   ├── 将 input_ids, attention_mask, labels 移到 device(GPU/CPU)
│       │   │   ├── torch.no_grad() 上下文 → 关闭梯度计算（节省内存）
│       │   │   ├── model(input_ids, attention_mask, labels) → 前向传播
│       │   │   ├── outputs[1] → 取出 logits（分类得分）
│       │   │   ├── logits.detach().cpu().numpy() → 从GPU转移到CPU转numpy
│       │   │   └── np.argmax(logits, axis=1) → 取得分最高的类别索引
│       │   └── 汇总所有预测结果 pred
│       │
│       └── 索引映射为类别名
│           └── [CATEGORY_NAME[x] for x in pred]
│               → 如 0→'Travel-Query', 2→'FilmTele-Play' 等
│
├─ 4. 成功/异常处理
└─ 5. 计算耗时 → 返回 Response
```

调用链 4：大语言模型 (GPT/Qwen) — `POST /v1/text-cls/gpt`



```
gpt_classify(req: TextClassifyRequest)
│
├─ 前置动作，加载提前训练好的 TF-IDF 模型权重，提取 dataset.csv 第一列种的数据的特征向量（TF-IDF 向量），得到 train_tfidf
├─ 1. 记录开始时间
├─ 2. 初始化空的 TextClassifyResponse
├─ 3. 调用 → model_for_gpt(req.request_text)    ← 核心
│       │
│       ├── 输入类型判断：str → 单条 / list → 批量 / 其他(抛异常)
│       │
│       ├── TF-IDF 特征化
│       │   └── tfidf.transform(request_text) → 待推理文本的 TF-IDF 向量
│       │
│       └── 对每条文本逐一执行：
│           │
│           ├── (a) 动态 Few-shot 样本检索
│           │   ├── np.dot(tfidf_feat[idx], train_tfidf.T)
│           │   │   → 计算待推理文本与训练集所有样本的余弦相似度
│           │   ├── argsort()[::-1][:10] → 取最相似的 Top-10 样本索引
│           │   └── 拼接为 "文本 -> 类别" 格式的参考示例字符串 dynamic_top10
│           │
│           ├── (b) 构造 Prompt（RAG + Few-shot）
│           │   └── PROMPT_TEMPLATE.format(
│           │         待识别文本,
│           │         Top-10 参考示例,
│           │         所有待选类别（"/"分隔）
│           │       )
│           │
│           └── (c) 调用 LLM API
│               ├── client = openai.Client(阿里云 DashScope 兼容接口)
│               ├── client.chat.completions.create(
│               │     model="qwen-plus",
│               │     messages=[{role: "user", content: prompt}],
│               │     temperature=0,    ← 确定性输出
│               │     max_tokens=64
│               │   )
│               └── response.choices[0].message.content → 类别名
│
├─ 4. 成功/异常处理
└─ 5. 计算耗时 → 返回 Response
```
