# config.py
KAFKA_BOOTSTRAP_SERVERS = "127.0.0.1:9092"
KAFKA_TOPIC_PDF = "pdf_upload_topic"

REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_DB = 0

# MinerU 输出目录
MINERU_OUTPUT_DIR = "./mineru_output"
# 检索知识库目录
CHROMA_PERSIST_DIR = "./chroma_mm_rag"
# 上传临时文件目录
UPLOAD_DIR = "./upload_files"
# 图片缓存目录
IMAGE_CACHE_DIR = "./static/images"

# 多模态大模型（qwen-vl）
LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_API_KEY = "your-dashscope-key"
LLM_MODEL = "qwen-vl-max"
