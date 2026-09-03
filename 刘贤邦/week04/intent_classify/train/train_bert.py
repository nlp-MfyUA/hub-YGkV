import pandas as pd
import numpy as np
import torch
import json

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from transformers import AutoTokenizer, BertForSequenceClassification, Trainer, TrainingArguments
from datasets import Dataset

# 加载和预处理数据
dataset_df = pd.read_csv("../assets/dataset/dataset.csv", sep='\t', header=None)

# 初始化 LabelEncoder，用于将文本标签转换为数字标签
lbl = LabelEncoder()
# 拟合数据并转换前500个标签，得到数字标签
labels = lbl.fit_transform(dataset_df[1].values[:500])
# 提取前500个文本内容
texts = list(dataset_df[0].values[:500])

# 需要将 ID -> label 的映射关系存下来
id2label = {idx: label for idx, label in enumerate(lbl.classes_)}
with open("../id2label.json", "w", encoding='utf-8') as f:
    json.dump(id2label, f, ensure_ascii=False, indent=4)

# 分割数据为训练集和测试集（此时的labels已经是数字了）
x_train, x_test, train_labels, test_labels = train_test_split(
    texts,
    labels,
    test_size=0.2,
    stratify=labels,
)

# 2.从预训练模型加载分词器和模型
tokenizer = AutoTokenizer.from_pretrained('bert-base-chinese')
model = BertForSequenceClassification.from_pretrained(
    'bert-base-chinese',
    num_labels=len(id2label)
)

# 3.使用分词器对训练集和测试集文本进行编码
train_encodings = tokenizer(x_train, truncation=True, padding=True, max_length=64)
test_encodings = tokenizer(x_test, truncation=True, padding=True, max_length=64)

# 4.将编码后的数据和标签转换为Dataset对象
train_dataset = Dataset.from_dict(
    {
        'input_ids': train_encodings['input_ids'],
        'attention_mask': train_encodings['attention_mask'],
        'labels': train_labels
    }
)
test_dataset = Dataset.from_dict({
    'input_ids': test_encodings['input_ids'],
    'attention_mask': test_encodings['attention_mask'],
    'labels': test_labels
})

# 定义用于计算评估指标的函数
def compute_metrics(eval_pred):
    # eval_pred 是一个元组，包含模型预测的logits 和真实的标签
    logits, labels = eval_pred
    # 找到最大值索引
    predictions = np.argmax(logits, axis=-1)
    # 计算预测准确率
    return {'accuracy': (predictions == labels).mean()}

# 配置训练参数
training_args = TrainingArguments(
    output_dir='../assets/weights/bert/',
    num_train_epochs=4,
    per_device_train_batch_size=16,
    per_device_eval_batch_size=16,
    warmup_steps=500,
    weight_decay=0.01,
    logging_dir='logs',
    logging_steps=100,
    eval_strategy='epoch',
    save_strategy='epoch',
    load_best_model_at_end=True
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=test_dataset,
    compute_metrics=compute_metrics,
)

trainer.train()
trainer.evaluate()

best_model_path = trainer.state.best_model_checkpoint
if best_model_path:
    best_model = BertForSequenceClassification.from_pretrained(best_model_path)
    print(f"The best model is located at: {best_model_path}")
    torch.save(best_model.state_dict(), '../assets/weights/bert.pt')
    print("Best model saved to assets/weights/bert.pt")
else:
    print("Could not find the best model checkpoint.")