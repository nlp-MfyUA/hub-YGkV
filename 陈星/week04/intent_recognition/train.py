"""训练离线 TF-IDF + LinearSVC 意图识别模型。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from joblib import dump
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from intent_classifier.config import DEFAULT_DATA_PATH, DEFAULT_MODEL_PATH, RANDOM_SEED


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--model-out", type=Path, default=DEFAULT_MODEL_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw_frame = pd.read_csv(args.data, sep="\t", header=None, names=["text", "label"])
    frame = raw_frame.dropna().drop_duplicates().reset_index(drop=True)
    x_train, x_test, y_train, y_test = train_test_split(
        frame["text"].astype(str),
        frame["label"].astype(str),
        test_size=0.2,
        random_state=RANDOM_SEED,
        stratify=frame["label"],
    )
    pipeline = Pipeline(
        [
            ("tfidf", TfidfVectorizer(analyzer="char", ngram_range=(1, 3), min_df=2, sublinear_tf=True)),
            ("classifier", LinearSVC(C=1.0)),
        ]
    )
    pipeline.fit(x_train, y_train)
    predictions = pipeline.predict(x_test)
    accuracy = float(accuracy_score(y_test, predictions))

    args.model_out.parent.mkdir(parents=True, exist_ok=True)
    dump(pipeline, args.model_out)
    report = {
        "raw_samples": len(raw_frame),
        "samples": len(frame),
        "removed_rows": len(raw_frame) - len(frame),
        "train_samples": len(x_train),
        "test_samples": len(x_test),
        "labels": sorted(frame["label"].unique().tolist()),
        "accuracy": accuracy,
        "classification_report": classification_report(y_test, predictions, output_dict=True),
    }
    report_path = args.model_out.parent / "metrics.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"训练完成：{len(frame)} 条，{len(report['labels'])} 类")
    print(f"测试集准确率：{accuracy:.4f}")
    print(f"模型：{args.model_out}")
    print(f"指标：{report_path}")


if __name__ == "__main__":
    main()
