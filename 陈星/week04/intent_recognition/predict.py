"""命令行预测示例。"""

import argparse

from intent_classifier import IntentClassifier


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("text", help="待识别文本")
    args = parser.parse_args()
    classifier = IntentClassifier()
    print(classifier.predict(args.text))


if __name__ == "__main__":
    main()
