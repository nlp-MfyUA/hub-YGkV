import re
from typing import Union, List

from config import REGEX_RULE
from logger import logger

REGEX_RULE_COMPILED = {}

for category in REGEX_RULE.keys():
    REGEX_RULE_COMPILED[category] = re.compile("|".join(REGEX_RULE[category]))


def model_for_regex(request_text: Union[str, List[str]]) -> Union[str, List[str]]:
    classify_result = []

    if isinstance(request_text, str):

        # 只要 request_text 中包含这个类别关键词（播放|电视剧）中一个关键词特征，就判断属于这个类别
        for category in REGEX_RULE_COMPILED.keys():
            if REGEX_RULE_COMPILED[category].findall(request_text):
                classify_result.append(category)
                break

        # 如果一句话中一个类别都匹配不到，则认为是Other
        if not classify_result:
            classify_result.append("Other")

    elif isinstance(request_text, list):

        # 1.遍历输入的列表
        for text in request_text:
            is_classified = False

            # 2.对列表中每个字符串判断分类结果
            for category in REGEX_RULE_COMPILED.keys():
                if REGEX_RULE_COMPILED[category].findall(text):
                    classify_result.append(category)
                    is_classified = True
                    break

            if not is_classified:
                classify_result.append("Other")

    else:
        raise Exception("格式不支持")

    return classify_result