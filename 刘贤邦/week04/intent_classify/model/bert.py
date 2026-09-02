from typing import Union, List

import numpy as np
import torch
import json
from torch.utils.data import Dataset, DataLoader
from transformers import AutoTokenizer, BertForSequenceClassification

from config import BERT_MODEL_PRETRAINED_PATH, BERT_MODEL_PKL_PATH

# 加载模型
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
tokenizer = AutoTokenizer.from_pretrained(BERT_MODEL_PRETRAINED_PATH)

# 加载映射
with open("id2label.json", "r", encoding="utf-8") as f:
    id2label = json.load(f)

# 用BertForSequenceClassification（训练时也是这个）来接受模型训练好后的权重
model = BertForSequenceClassification.from_pretrained(BERT_MODEL_PRETRAINED_PATH, num_labels=len(id2label))

# 加载权重到现有模型
model.load_state_dict(torch.load(BERT_MODEL_PKL_PATH))
model.to(device)

# 1.定义接受数据集
class NewsDataset(Dataset):
    def __init__(self, encodings):
        self.encodings = encodings

    def __len__(self):
        return len(self.encodings['input_ids'])

    def __getitem__(self, idx):
        return {key: torch.tensor(val[idx]) for key, val in self.encodings.items()}


def model_for_bert(request_text: Union[str, List[str]]) -> Union[str, List[str]]:

    # 输入处理
    if isinstance(request_text, str):
        request_text = [request_text]
    elif isinstance(request_text, list):
        pass
    else:
        raise Exception("格式不支持")

    # 1.文本编码
    # 得到一个列表对象，里面的元素是一个个字典，字典就是某个字符串的编码结果
    test_encoding = tokenizer(request_text, truncation=True, padding=True, max_length=30)
    print(test_encoding)

    # 2.Token序列转变成batch
    test_dataset = NewsDataset(test_encoding)
    test_dataloader = DataLoader(test_dataset, batch_size=16, shuffle=False)

    # 3.使用模型
    model.eval()
    prediction = []

    # 4.遍历数据集
    for batch in test_dataloader:
        with torch.no_grad():
            input_ids = batch['input_ids'].to(device)
            attention_mask = batch['attention_mask'].to(device)

            # 前向传播
            outputs = model(input_ids, attention_mask=attention_mask)

        # 使用属性logits取出得到分数
        logits = outputs.logits
        logits = logits.detach().cpu().numpy()

        prediction += list(np.argmax(logits, axis=-1).flatten())

    #
    classify_result = [id2label[str(x)] for x in prediction]

    return classify_result
