from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from intent_classifier import IntentClassifier


def test_music_intent() -> None:
    model = IntentClassifier()
    assert model.predict("帮我播放周杰伦的歌曲") == "Music-Play"


def test_weather_intent() -> None:
    model = IntentClassifier()
    assert model.predict("明天北京会下雨吗") == "Weather-Query"


def test_batch_prediction() -> None:
    model = IntentClassifier()
    result = model.predict_batch(["打开空调", "设置明早七点的闹钟"])
    assert result == ["HomeAppliance-Control", "Alarm-Update"]
