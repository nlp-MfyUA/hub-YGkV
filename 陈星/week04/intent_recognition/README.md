# 作业2：意图识别项目（Vibe Coding 独立实现）

这是一个完全离线、可复现的中文意图识别项目。字符级 TF-IDF 能直接处理中文，不依赖在线停用词，也不需要云端 API 密钥；LinearSVC 负责 12 类意图分类。

## 完整过程

1. `data/dataset.csv`：读取制表符分隔的文本与标签，删除空值和完全重复记录。
2. `train.py`：先完成去重，再固定随机种子，按标签分层切分 80% 训练集、20% 测试集，避免重复样本跨越训练集和测试集。
3. 特征：字符 1～3 gram TF-IDF；模型：LinearSVC。
4. 训练后输出 `artifacts/intent_model.joblib` 与 `artifacts/metrics.json`。
5. `predict.py` / `IntentClassifier`：加载训练产物并完成单条或批量预测。
6. `tests/test_service.py`：验证音乐、天气、家电和闹钟等典型输入。

## 运行

```powershell
python train.py
python predict.py "帮我播放周杰伦的歌曲"
python -m pytest -q
```

## 为什么这样设计

- 【重点】训练/推理解耦：服务只加载模型，不在每次请求时重复训练。
- 【重点】先去重再切分：防止相同样本同时出现在训练集和测试集，造成数据泄漏。
- 【掌握】分层切分：训练集与测试集保持类别比例一致。
- 【掌握】Pipeline：保证训练和预测使用完全相同的特征处理。
- 【了解】字符 n-gram：对中文短句、未登录词和轻微表达变化更稳健。

## 可继续升级

把 Pipeline 替换为 BERT 分类器，并保留相同的 `IntentClassifier` 接口，即可从传统机器学习平滑升级到深度学习模型。
