"""批量评测执行器（技术设计文档 §9.3）。

用法：
    python eval/run_eval.py --dataset eval/dataset --provider qwen --out eval/report.md
    python eval/run_eval.py --limit 10 --concurrency 2

labels.csv 格式：filename,true_label（true_label 为中文五类之一）。
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# 保证无论从哪个工作目录启动都能导入 backend 包
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.arbiter import arbitrate
from backend.config import Settings, get_settings
from backend.errors import ApiError
from backend.prompt import SYSTEM_PROMPT, USER_TEXT
from backend.providers import build_provider
from backend.providers.base import VisionProvider
from backend.schemas import ModelOutput
from backend.utils import encode_image, parse_model_json
from pydantic import ValidationError

from eval.metrics import EvalOutcome, build_report

MIME_BY_FORMAT = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


@dataclass
class Sample:
    filename: str
    true_label: str
    path: Path


def load_labels(dataset_dir: Path) -> list[Sample]:
    """读取 labels.csv；缺失文件 / 缺失图片给出可读报错。"""
    csv_path = dataset_dir / "labels.csv"
    if not csv_path.exists():
        raise SystemExit(f"找不到 {csv_path}，请按 README 说明准备评测集（filename,true_label）")

    samples: list[Sample] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "filename" not in reader.fieldnames:
            raise SystemExit(f"{csv_path} 缺少表头 filename,true_label")
        for i, row in enumerate(reader, start=2):
            name = (row.get("filename") or "").strip()
            label = (row.get("true_label") or "").strip()
            if not name or not label:
                print(f"[警告] labels.csv 第 {i} 行有空字段，已跳过", file=sys.stderr)
                continue
            path = dataset_dir / name
            if not path.exists():
                print(f"[警告] 图片不存在，已跳过：{path}", file=sys.stderr)
                continue
            samples.append(Sample(filename=name, true_label=label, path=path))
    if not samples:
        raise SystemExit(f"{csv_path} 中没有可用样本")
    return samples


def sniff_mime(data: bytes) -> str:
    from PIL import Image
    import io

    try:
        with Image.open(io.BytesIO(data)) as im:
            return MIME_BY_FORMAT.get((im.format or "").upper(), "image/jpeg")
    except Exception:
        return "image/jpeg"


async def run_one(provider: VisionProvider, sample: Sample) -> EvalOutcome:
    """单样本：读取 → 编码 → 调用（含退避重试）→ 解析 → 裁决。"""
    data = sample.path.read_bytes()
    b64 = encode_image(data)
    mime = sniff_mime(data)

    last_err: ApiError | None = None
    for attempt in range(2):  # 失败自动退避重试一次（1s / 2s）
        try:
            raw = await provider.analyze(b64, SYSTEM_PROMPT, USER_TEXT, mime=mime)
            model_out = ModelOutput(**parse_model_json(raw.text))
            final, override = arbitrate(model_out)
            return EvalOutcome(
                filename=sample.filename, true_label=sample.true_label,
                predicted=final, arbiter_override=override,
                latency_ms=raw.latency_ms, status="ok",
                evidence=model_out.evidence,
            )
        except (ApiError, ValidationError) as exc:
            last_err = exc if isinstance(exc, ApiError) else ApiError(str(exc))
            if attempt == 0:
                await asyncio.sleep(1.0 * (attempt + 1))
    return EvalOutcome(
        filename=sample.filename, true_label=sample.true_label,
        predicted=None, status="parse_fail",
        error=last_err.detail if last_err else "unknown",
    )


async def run_eval(provider: VisionProvider, samples: list[Sample],
                   concurrency: int, on_progress=None) -> list[EvalOutcome]:
    """默认并发 1（避免触发限流）；--concurrency K 时按 K 并发。"""
    sem = asyncio.Semaphore(max(1, concurrency))
    done = 0

    async def guarded(s: Sample) -> EvalOutcome:
        nonlocal done
        async with sem:
            outcome = await run_one(provider, s)
            done += 1
            if on_progress:
                on_progress(done, len(samples), outcome)
            return outcome

    return await asyncio.gather(*(guarded(s) for s in samples))


def build_settings(provider_override: str | None) -> Settings:
    settings = get_settings()
    if provider_override and provider_override != settings.vision_provider:
        settings = settings.model_copy(update={"vision_provider": provider_override})
    if not settings.active_api_key or not settings.active_base_url:
        raise SystemExit(
            f"provider {settings.vision_provider!r} 未配置：请在 .env 填写 "
            f"{settings.vision_provider.upper()}_API_KEY / _BASE_URL"
        )
    return settings


def main() -> None:
    parser = argparse.ArgumentParser(description="楼道消防风险识别批量评测")
    parser.add_argument("--dataset", default="eval/dataset", help="评测集目录（含 labels.csv）")
    parser.add_argument("--provider", default=None, choices=["deepseek", "qwen"],
                        help="覆盖 .env 中的 VISION_PROVIDER")
    parser.add_argument("--out", default="eval/report.md", help="报告输出路径")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条")
    parser.add_argument("--concurrency", type=int, default=1, help="并发数（默认 1，防限流）")
    args = parser.parse_args()

    t0 = time.perf_counter()
    samples = load_labels(Path(args.dataset))
    if args.limit:
        samples = samples[: args.limit]

    settings = build_settings(args.provider)
    provider = build_provider(settings)
    print(f"provider={settings.vision_provider} model={settings.active_model} "
          f"samples={len(samples)} concurrency={args.concurrency}")

    def on_progress(done: int, total: int, o: EvalOutcome) -> None:
        mark = "✓" if o.predicted == o.true_label else "✗"
        print(f"  [{done}/{total}] {mark} {o.filename} 真实={o.true_label} "
              f"预测={o.predicted or o.status} ({o.latency_ms} ms)")

    outcomes = asyncio.run(run_eval(provider, samples, args.concurrency, on_progress))
    report = build_report(outcomes, dataset=args.dataset,
                          provider=settings.vision_provider, model=settings.active_model)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    ok = sum(1 for o in outcomes if o.predicted == o.true_label)
    parsed = sum(1 for o in outcomes if o.status == "ok")
    print(f"\n完成：准确率 {ok}/{parsed}（解析失败 {len(outcomes) - parsed}），"
          f"总耗时 {time.perf_counter() - t0:.1f}s")
    print(f"报告已写入 {out_path}")


if __name__ == "__main__":
    main()
