REGEX_RULE = {
    "FilmTele-Play": ["播放", "电视剧"], # 句子是不是包含特定的单词，做出分类
    "HomeAppliance-Control": ["空调", "广播"]
}

# 该模型还没有训练
TFIDF_MODEL_PKL_PATH = "assets/weights/tfidf_ml.pkl"

BERT_MODEL_PKL_PATH = "assets/weights/bert.pt"    # bert模型微调后的权重
BERT_MODEL_PRETRAINED_PATH = "bert-base-chinese"  # bert模型原始的权重

LLM_OPENAI_SERVER_URL = f"https://dashscope.aliyuncs.com/compatible-mode/v1" # ollama
LLM_OPENAI_API_KEY = "sk"
LLM_MODEL_NAME = "qwen-plus"