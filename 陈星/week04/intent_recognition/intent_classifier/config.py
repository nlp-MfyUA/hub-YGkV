from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_PATH = PROJECT_ROOT / "data" / "dataset.csv"
DEFAULT_MODEL_PATH = PROJECT_ROOT / "artifacts" / "intent_model.joblib"
RANDOM_SEED = 42
