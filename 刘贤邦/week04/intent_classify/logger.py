import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),   # 输出log到app.log文件
        logging.StreamHandler(),         # 同时输出到控制台
    ]
)

logger = logging.getLogger(__name__)