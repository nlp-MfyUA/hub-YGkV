"""Week04 作业1：BERT 中文意图分类微调与超参数对比。

示例：
python bert_finetune_experiment.py --learning-rate 2e-5 --run-name lr_2e-5
python bert_finetune_experiment.py --learning-rate 5e-5 --run-name lr_5e-5
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from datasets import Dataset
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from transformers import (
    BertForSequenceClassification,
    BertTokenizer,
    Trainer,
    TrainingArguments,
)


DEFAULT_DATA = Path(
    r"D:\BaiduNetdiskDownload\第03周-语言模型与Agent基础\Week03-课程代码"
    r"\01-intent-classify\assets\dataset\dataset.csv"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="微调 bert-base-chinese 做意图分类")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--model", default="google-bert/bert-base-chinese")
    parser.add_argument("--sample-size", type=int, default=500)
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--run-name", default="bert_baseline")
    parser.add_argument("--output-root", type=Path, default=Path("experiment_results"))
    parser.add_argument("--save-model", action="store_true", help="额外保存完整模型权重")
    return parser.parse_args()


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def compute_metrics(eval_pred) -> dict[str, float]:
    logits, labels = eval_pred
    predictions = np.argmax(logits, axis=-1)
    return {"accuracy": float((predictions == labels).mean())}


def main() -> None:
    args = parse_args()
    set_seed(args.seed)
    run_dir = args.output_root / args.run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    frame = pd.read_csv(args.data, sep="\t", header=None, names=["text", "label"])
    frame = frame.iloc[: args.sample_size].dropna().reset_index(drop=True)
    encoder = LabelEncoder()
    labels = encoder.fit_transform(frame["label"].astype(str))
    texts = frame["text"].astype(str).tolist()

    x_train, x_test, y_train, y_test = train_test_split(
        texts,
        labels,
        test_size=0.2,
        stratify=labels,
        random_state=args.seed,
    )

    print(f"设备: {'CUDA' if torch.cuda.is_available() else 'CPU'}")
    print(f"样本: train={len(x_train)}, test={len(x_test)}, 类别={len(encoder.classes_)}")
    print(
        f"超参数: epochs={args.epochs}, batch_size={args.batch_size}, "
        f"learning_rate={args.learning_rate:g}, seed={args.seed}"
    )

    tokenizer = BertTokenizer.from_pretrained(args.model)
    model = BertForSequenceClassification.from_pretrained(
        args.model,
        num_labels=len(encoder.classes_),
        id2label={i: label for i, label in enumerate(encoder.classes_)},
        label2id={label: i for i, label in enumerate(encoder.classes_)},
    )

    train_tokens = tokenizer(x_train, truncation=True, padding=True, max_length=64)
    test_tokens = tokenizer(x_test, truncation=True, padding=True, max_length=64)
    train_dataset = Dataset.from_dict({**train_tokens, "labels": y_train})
    test_dataset = Dataset.from_dict({**test_tokens, "labels": y_test})

    args_for_trainer = TrainingArguments(
        output_dir=str(run_dir / "checkpoints"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        warmup_ratio=0.1,
        weight_decay=0.01,
        logging_steps=5,
        eval_strategy="epoch",
        save_strategy="no",
        load_best_model_at_end=False,
        report_to="none",
        seed=args.seed,
        data_seed=args.seed,
        use_cpu=not torch.cuda.is_available(),
    )
    trainer = Trainer(
        model=model,
        args=args_for_trainer,
        train_dataset=train_dataset,
        eval_dataset=test_dataset,
        compute_metrics=compute_metrics,
    )

    train_result = trainer.train()
    metrics = trainer.evaluate()
    if args.save_model:
        trainer.save_model(str(run_dir / "model"))
        tokenizer.save_pretrained(str(run_dir / "model"))

    result = {
        "run_name": args.run_name,
        "model": args.model,
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "samples": len(frame),
        "train_samples": len(x_train),
        "test_samples": len(x_test),
        "num_labels": len(encoder.classes_),
        "labels": encoder.classes_.tolist(),
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "seed": args.seed,
        "train_runtime_seconds": train_result.metrics.get("train_runtime"),
        "eval_loss": metrics.get("eval_loss"),
        "eval_accuracy": metrics.get("eval_accuracy"),
        "model_saved": args.save_model,
    }
    (run_dir / "metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n最终结果")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
