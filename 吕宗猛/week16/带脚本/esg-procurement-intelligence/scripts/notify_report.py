#!/usr/bin/env python3
"""Preview or deliver an existing report using installation-time configuration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if (SCRIPT_DIR / "_notifications").is_dir():
    from _notifications import (ConfigurationError, SecretError, SecretStore, send_report,
                                user_data_root)
else:
    sys.path.insert(0, str(SCRIPT_DIR.parent))
    from shared.notifications import (ConfigurationError, SecretError, SecretStore, send_report,
                                      user_data_root)


def load_config(path: Path) -> dict:
    if not path.exists():
        return {"channels": ["codex"], "external_send_authorized": False}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ConfigurationError("Notification configuration must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path, help="Existing UTF-8 Markdown report")
    parser.add_argument("--title", help="Report notification title")
    parser.add_argument("--summary-file", type=Path, help="Optional reviewed Markdown summary")
    parser.add_argument("--report-id", help="Stable report identity, such as monthly-shenhua-2026-10")
    parser.add_argument("--config", type=Path, default=user_data_root() / "notifications.json")
    parser.add_argument("--state", type=Path, default=user_data_root() / "state" / "delivery.json")
    parser.add_argument("--send", action="store_true", help="Deliver to installation-authorized targets")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        channels = config.get("channels") or ["codex"]
        if isinstance(channels, str):
            channels = [part.strip() for part in channels.split(",") if part.strip()]
        external = any(channel != "codex" for channel in channels)
        if args.send and external and config.get("external_send_authorized") is not True:
            raise ConfigurationError("External delivery must be authorized during installation first")
        summary = (args.summary_file.read_text(encoding="utf-8-sig")
                   if args.summary_file else None)
        result = send_report(config, args.report.resolve(), title=args.title,
                             report_id=args.report_id, summary=summary,
                             state_path=args.state.resolve(), send=args.send,
                             secret_store=(SecretStore(config["secrets_root"])
                                           if args.send and external and config.get("secrets_root")
                                           else None))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("overall_status") in ("preview", "success", "skipped", "codex") else 1
    except (ConfigurationError, SecretError) as error:
        print(json.dumps({"overall_status": "configuration_error", "error": str(error)},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError):
        # Filesystem paths and arbitrary exception text can contain private values.
        print(json.dumps({"overall_status": "input_error",
                          "error": "Report, summary, configuration or state could not be read"}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
