from __future__ import annotations

from pathlib import Path
from typing import Iterable

from joblib import load

from .config import DEFAULT_MODEL_PATH


class IntentClassifier:
    """加载训练产物并提供单条/批量预测。"""

    def __init__(self, model_path: Path = DEFAULT_MODEL_PATH) -> None:
        self.pipeline = load(model_path)

    def predict(self, text: str) -> str:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text 必须是非空字符串")
        return str(self.pipeline.predict([text.strip()])[0])

    def predict_batch(self, texts: Iterable[str]) -> list[str]:
        clean = [text.strip() for text in texts if isinstance(text, str) and text.strip()]
        if not clean:
            raise ValueError("texts 至少包含一条非空字符串")
        return [str(label) for label in self.pipeline.predict(clean)]
