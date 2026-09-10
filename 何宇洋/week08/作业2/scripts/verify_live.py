"""显式启用的一次真实研究；API 在进程内调用，检索、抓取与模型均使用真实服务。"""
import argparse
import json
from pathlib import Path
import sys
import time

# 允许从项目根目录直接执行 python scripts/verify_live.py。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from research_assistant.api import create_app
from research_assistant.config import Settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="明确启用真实模型用量与联网检索")
    parser.add_argument("--topic", default="Python 中 asyncio 与线程分别适合哪些 I/O 任务？优先 Python 官方文档，明确使用限制。")
    args = parser.parse_args()
    if not args.live:
        parser.error("真实验收需要 --live，将产生实际 API 用量")
    settings = Settings.from_env()
    if errors := settings.configuration_errors():
        print(json.dumps({"configuration_errors": errors}, ensure_ascii=False))
        return 2
    with TestClient(create_app(settings)) as client:
        response = client.post("/research", json={"topic": args.topic})
        response.raise_for_status()
        job_id = response.json()["id"]
        print(json.dumps({"id": job_id, "limits": {"rounds": 2, "pages": 8, "seconds": 300}}, ensure_ascii=False), flush=True)
        deadline = time.monotonic() + 310
        next_log = 0
        while time.monotonic() < deadline:
            status = client.get(f"/research/{job_id}").json()
            if time.monotonic() >= next_log or status["status"] != "running":
                print(json.dumps({k: status[k] for k in ["status", "stage", "rounds", "pages_attempted", "pages_read", "elapsed_seconds", "usage"]}, ensure_ascii=False), flush=True)
                next_log = time.monotonic()+15
            if status["status"] != "running":
                break
            time.sleep(1)
        else:
            print("任务超过验收等待上限")
            return 1
        report_response = client.get(f"/research/{job_id}/report")
        markdown = client.get(f"/research/{job_id}/report?format=markdown")
        report_response.raise_for_status()
        report = report_response.json()
        events = client.get(f"/research/{job_id}/events").json()["events"]
        sources = {s["id"]: s for s in report["sources"]}
        evidence = {e["id"]: e for e in report["evidence"]}
        claims = [*report["summary"], *report["key_conclusions"],
                  *(c for section in report["sections"] for c in section["claims"])]
        citations = [c for claim in claims for c in claim["citations"]]
        checks = {
            "terminal_with_evidence": status["status"] in ("completed", "partial") and bool(evidence),
            "sources_read": bool(sources) and any(e["kind"] == "page_read" for e in events),
            "citations_resolve": bool(citations) and all(
                c["evidence_id"] in evidence and c["source_id"] in sources
                and c["url"] == sources[c["source_id"]]["url"]
                and c["quote"] == evidence[c["evidence_id"]]["quote"] for c in citations),
            "report_download": markdown.status_code == 200 and "## 关键结论" in markdown.text,
            "budget_respected": status["rounds"] <= 2 and status["pages_attempted"] <= 8
                                and status["elapsed_seconds"] < 305,
            "usage_recorded": status["usage"]["calls_with_usage"] > 0,
        }
        result = {"id": job_id, "status": status["status"], "checks": checks,
                  "sources": len(sources), "evidence": len(evidence), "usage": status["usage"],
                  "stop_reason": status["stop_reason"], "errors": status["errors"]}
        (settings.output_dir / job_id / "acceptance.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
