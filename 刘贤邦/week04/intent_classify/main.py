from fastapi import FastAPI
import time

from data_schema import TextClassifyRequest, TextClassifyResponse
from logger import logger
from model.regex_rule import model_for_regex
from model.tfidf import model_for_tfidf
from model.bert import model_for_bert
from model.prompt import model_for_gpt

app = FastAPI()


# 定义四个路径处理函数

# 正则表达式
@app.post("/v1/text-cls/regex")
def regex_classify(req: TextClassifyRequest) -> TextClassifyResponse:
    """
    利用正则表达式进行文本分类

    :param req: 请求体
    :return: 响应体
    """
    start_time = time.time()
    response = TextClassifyResponse(
        request_id = req.request_id,
        request_text = req.request_text,
        classify_result="",
        classify_time=0,
        error_msg=""
    )

    logger.info(f"{req.request_id} {req.request_text}")  # 打印请求

    try:
        response.classify_result = model_for_regex(req.request_text)
        response.error_msg = "ok"
    except Exception as e:
        response.classify_result = "error"
        response.error_msg = str(e)

    response.classify_time = round(time.time() - start_time, 3)
    return response


# TF-IDF+SVM
@app.post("/v1/text-cls/tfidf")
def tfidf_classify(req: TextClassifyRequest) -> TextClassifyResponse:
    """
    利用TFIDF进行文本分类
    :param req:
    :return:
    """
    start_time = time.time()
    response = TextClassifyResponse(
        request_id = req.request_id,
        request_text = req.request_text,
        classify_result="",
        classify_time=0,
        error_msg=""
    )
    logger.info(f"Get request:{req.request_id} {req.request_text}")

    try:
        response.classify_result = model_for_tfidf(req.request_text)
        response.error_msg = "ok"
    except Exception as e:
        response.classify_result = "error"
        response.error_msg = str(e)

    response.classify_time = round(time.time() - start_time, 3)
    return response


# BERT
@app.post("/v1/text-cls/bert")
def bert_classify(req: TextClassifyRequest) -> TextClassifyResponse:
    """
    利用BERT模型微调进行文本分类
    :param req:
    :return:
    """
    start_time = time.time()

    response = TextClassifyResponse(
        request_id = req.request_id,
        request_text = req.request_text,
        classify_result="",
        classify_time=0,
        error_msg=""
    )

    logger.info(f"Get request:{req.request_id} {req.request_text}")
    try:
        response.classify_result = model_for_bert(req.request_text)
        response.error_msg = "ok"
    except Exception as e:
        response.classify_result = "error"
        response.error_msg = str(e)

    response.classify_time = round(time.time() - start_time, 3)
    return response


# GPT + TFIDF打分 + Prompt
@app.post("/v1/text-cls/gpt")
def gpt_classify(req: TextClassifyRequest) -> TextClassifyResponse:
    """
    利用大语言模型进行文本分类
    :param req:
    :return:
    """
    start_time = time.time()
    response = TextClassifyResponse(
        request_id = req.request_id,
        request_text = req.request_text,
        classify_result="",
        classify_time=0,
        error_msg=""
    )

    logger.info(f"Get request:{req.request_id} {req.request_text}")

    try:
        response.classify_result = model_for_gpt(req.request_text)

        logger.info(f"Get:{response.classify_result}")

        response.error_msg = "ok"
    except Exception as e:
        response.classify_result = "error"
        response.error_msg = str(e)

    response.classify_time = round(time.time() - start_time, 3)
    return response