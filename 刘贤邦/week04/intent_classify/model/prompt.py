from typing import Union, List

import pandas as pd
import numpy as np
import openai
from joblib import load

from config import LLM_OPENAI_SERVER_URL, LLM_OPENAI_API_KEY, LLM_MODEL_NAME, TFIDF_MODEL_PKL_PATH


# 1.加载TFIDF模型和数据集
tfidf, _ = load(TFIDF_MODEL_PKL_PATH)
train_data = pd.read_csv("assets/dataset/dataset.csv", sep='\t', header=None)

# 2.使用TFIDF对数据集（列表）的特征转换，输出一个TFIDF向量的列表。而train_data[1]就是这个TFIDF向量的类别
train_tfidf = tfidf.transform(train_data[0])

# 3.定义大模型客户端和prompt模板
client = openai.Client(base_url=LLM_OPENAI_SERVER_URL, api_key=LLM_OPENAI_API_KEY)

PROMPT_TEMPLATE = """你是一个意图识别专家，请结合待选类别和参考例子进行意图分类。
待选类别：{2}

历史参考例子如下：
{1}

待识别文本为：{0}
只需要输出意图类别（从待选类别中选一个），不要其他输出。
"""

# 4.定义处理接口
# 每一篇文章都可以编码为一个TFIDF向量(word_num维)，该向量是词表中每个词在这篇文章的TFIDF值的组合，没有的值就输出0
# 最终所有文章组成一个二维向量 (n, word_num)
def model_for_gpt(request_text: Union[str, List[str]]) -> List[str]:
    classify_result = []

    if isinstance(request_text, str):
        # 4.1 对接收的数据也通过TFIDF转换为向量（特征）
        tfidf_feat = tfidf.transform([request_text])
        # 4.2 将request_text都转为列表，后期好处理
        request_text = [request_text]
    elif isinstance(request_text, list):
        tfidf_feat = tfidf.transform(request_text)
    else:
        raise Exception("格式不支持")

    # 4.3 遍历请求列表和列表索引（这里可以完全使用enumerate(request_text)，tfidf_feat的第0为就是样本的个数）
    for query_text, idx in zip(request_text, range(tfidf_feat.shape[0])):
        # 4.4 计算余弦相似度并找到前10个相似的例子
        ids = np.dot(tfidf_feat[idx], train_tfidf.T)  # (1, word_num) · (word_num, n)
        # 由于TFIDF向量是scipy.sparse.csr_matrix——稀疏矩阵类型，而非ndarray，需要先toarray转为ndarray
        # argsort()——返回升序排序的索引（小的在前）
        # [::-1]用于反转顺序 [:10]用于截取前10个
        top10_index = ids.toarray()[0].argsort()[::-1][:10]

        # 4.5 将相似例子组织为一个字符串
        dynamic_top10 = ""
        for similar_row in train_data.iloc[top10_index].iterrows():
            dynamic_top10 += similar_row[1][0] + " -> " + similar_row[1][1] + "\n"

        # 4.6 将提示词模板中的0,1,2更换为对应参数，同时设置随机性为最低（0），将提示词发给大模型
        response = client.chat.completions.create(
            model=LLM_MODEL_NAME,
            messages=[
                {"role": "user",
                 "content": PROMPT_TEMPLATE.format(
                     query_text, dynamic_top10, '/'.join(list(train_data[1].unique()))
                 )}
            ],
            temperature=0,
            max_tokens=4096   # 这个长度最好写大一点，因为模型的思考也算token
        )

        # 4.7 解析大模型的响应
        classify_result.append(response.choices[0].message.content)

    return classify_result