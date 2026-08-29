import torch
from sentence_transformers import SentenceTransformer

# 训练文本
sentences = [
    "我喜欢机器学习",
    "我喜欢深度学习",
    "我今天心情很不错"
]
# 用户输入文本
input_sentence = "我今天很开心"
# 定义模型目录
model_dir = './assets/model/BAAI/bge-small-zh-v1.5'

# 加载模型权重
model = SentenceTransformer(model_dir)
print(f'模型:{model_dir}加载完毕')
print('*' * 50)
# 对已有文本向量化
emb_sentences = model.encode(sentences)
# 对用户输入向量化
emb_input = model.encode(input_sentence)
# 获取两个向量的相似度，最终结果为A行B列的矩阵
result_similary = model.similarity(emb_input, emb_sentences)
# 利用argmax获取相似度最高的下标索引
max_similary_index = torch.argmax(result_similary).item()
# 输出用户原始输入文本
print(f'用户输入文本:\n  {input_sentence}')
print('*' * 50)
print(f'待选文本：\n  {'\n  '.join(sentences)}')
print('*' * 50)
# 根据下标索引获取并输出相似度最高的原有文本
print(f'语义相似度最高的文本为:\n  {sentences[max_similary_index]}')
print('*' * 50)
# 获取最高的相似度，并保留6位小数做输出
print(f'语义相似度最高为:\n  {result_similary[0, max_similary_index].item():.6f}')
