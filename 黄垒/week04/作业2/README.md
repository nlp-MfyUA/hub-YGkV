# 意图识别Vibe Coding
##  目录结构
agent-test_coding/                          # 当前项目根（D:\Works\agent_codes\agent-test_coding）
├── config/                                 # 配置层
│   ├── __init__.py
│   └── settings.py                         # 全局配置：路径/标签/LLM参数（支持 .env 覆盖）
├── app/                                    # 应用层
│   ├── main.py                             # FastAPI 入口（uvicorn app.main:app）
│   ├── core/
│   │   └── config.py                       # 核心配置出口（settings 单例）
│   ├── data/                               # 数据层
│   │   ├── loader.py                       # 数据集加载 + 分层划分
│   │   └── preprocess.py                   # jieba 分词 + 停用词过滤
│   ├── schemas/
│   │   └── intent.py                       # Pydantic 请求/响应模型
│   ├── models/                             # 算法层（4 条路线）
│   │   ├── base.py                         # 抽象基类 + 统一 Prediction
│   │   ├── regex_model.py                  # 路线1 正则关键词
│   │   ├── tfidf_svc_model.py              # 路线2 TF-IDF+LinearSVC
│   │   ├── bert_model.py                   # 路线3 BERT 微调
│   │   └── llm_model.py                    # 路线4 大模型+Few-shot
│   ├── services/
│   │   └── intent_service.py               # 模型注册表 + 统一预测编排
│   └── api/routes/
│       └── intent.py                       # HTTP 路由：/api/intent/*
├── training/                               # 训练/构建脚本
│   ├── common.py
│   ├── build_regex.py                      # 生成路线1 规则
│   ├── build_llm_examples.py               # 生成路线4 few-shot 示例
│   ├── train_tfidf.py                      # 训练路线2
│   └── train_bert.py                       # 微调路线3
├── tests/
│   ├── smoke_test.py                       # HTTP 端到端冒烟测试
│   └── test_models_local.py                # 本地模型封装测试
├── dataset/                                # 训练数据
│   ├── dataset.csv                         # 12100 条，12 个意图
│   └── baidu_stopwords.txt
├── models/                                 # 模型产物（脚本生成，见下）
├── requirements.txt
├── .env.example                            # 环境变量样例（LLM_API_KEY 等）
├── .gitignore
└── README.md

## 模型产物
models/
├── labels.json                        # 全局标签列表（12 个意图）
├── intent_regex/patterns.json         # 路线1 规则（447 关键词 + 180 子串正则）
├── intent_tfidf_svc/                  # 路线2
│   ├── vectorizer.pkl
│   ├── model.pkl
│   ├── labels.json
│   └── metrics.json                   # 准确率 0.9070
├── intent_bert_finetuned/             # 路线3（微调产物，准确率 0.9417）
│   ├── config.json / model.safetensors / tokenizer 文件
│   ├── labels.json
│   └── metrics.json
│   └── checkpoint-1210/ checkpoint-1815/   # 训练中间 checkpoint（可清理）
└── llm_fewshot/examples.json          # 路线4 few-shot 示例（24 条）

## 分层架构
HTTP 请求
  → app.api.routes.intent        (HTTP/路由层)
  → app.services.intent_service  (服务编排层：模型注册表)
  → app.models.*                 (算法层：4 个模型实现)
  → app.data.preprocess / models产物 / 远程API
  → 统一 Prediction → JSON 响应