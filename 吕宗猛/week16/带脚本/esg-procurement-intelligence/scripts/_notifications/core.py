"""Explicit-send report notifications with bounded transport and durable receipts.

All default operations are previews. The caller owns authorization and scheduling.
Codex results are returned to the host; this module does not create OS notifications.
"""

from __future__ import annotations

import base64
import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.headerregistry import Address
from email.message import EmailMessage
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import smtplib
import socket
import ssl
import tempfile
import time
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request

from .secrets import SecretError, SecretStore, user_data_root, validate_reference


class ConfigurationError(ValueError):
    """Configuration problem whose message does not contain secret values."""


@dataclass
class HttpResponse:
    status: int
    body: bytes | str
    headers: dict[str, str] = field(default_factory=dict)


def normalize_recipients(value: str | list[str]) -> list[str]:
    if isinstance(value, str):
        values = re.split(r"[,;\r\n]+", value)
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        values = value
    else:
        raise ConfigurationError("Recipients must be an address or a list of addresses")
    result, seen = [], set()
    for item in values:
        address = item.strip()
        if not address:
            continue
        if any(c in address for c in "\r\n:<>\x00"):
            raise ConfigurationError("Recipient must be a plain email address")
        try:
            parsed = Address(addr_spec=address)
        except (ValueError, IndexError):
            raise ConfigurationError("Invalid recipient email address") from None
        if not parsed.username or not parsed.domain or any(c.isspace() for c in address):
            raise ConfigurationError("Invalid recipient email address")
        canonical = parsed.username + "@" + parsed.domain.lower()
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    if not result:
        raise ConfigurationError("At least one recipient is required")
    return result


def _bounded_number(value: Any, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise ConfigurationError(name + " must be an integer")
    if not low <= value <= high:
        raise ConfigurationError(name + " is outside its allowed range")
    return int(value)


def validate_config(config: dict[str, Any] | None, *, _validate_channels: bool = True) -> dict[str, Any]:
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ConfigurationError("Notification configuration must be a JSON object")
    output = copy.deepcopy(config)
    channels = output.get("channels") or ["codex"]
    if isinstance(channels, str):
        channels = [part.strip() for part in channels.split(",") if part.strip()]
    if not isinstance(channels, list) or not channels:
        raise ConfigurationError("Select at least one notification channel")
    if any(channel not in ("codex", "email", "wecom", "dingtalk") for channel in channels):
        raise ConfigurationError("Unknown notification channel")
    output["channels"] = list(dict.fromkeys(channels))
    output["timeout"] = _bounded_number(output.get("timeout", 15), "timeout", 1, 30)
    output["max_attempts"] = _bounded_number(output.get("max_attempts", 3), "max_attempts", 1, 3)
    if not _validate_channels:
        return output
    for channel in output["channels"]:
        if channel == "codex":
            continue
        options = output.get(channel)
        if not isinstance(options, dict):
            raise ConfigurationError("Selected " + channel + " channel needs configuration")
        if any(name in options for name in ("password", "webhook", "secret")):
            raise ConfigurationError("Use secret reference fields instead of inline credentials")
        fields = {"email": ("password_ref",), "wecom": ("webhook_ref",),
                  "dingtalk": ("webhook_ref", "secret_ref")}[channel]
        for name in fields:
            try:
                validate_reference(options.get(name))
            except SecretError:
                raise ConfigurationError(channel + " needs a valid " + name) from None
        if channel == "email":
            for name in ("smtp_host", "username", "from_address"):
                if not isinstance(options.get(name), str) or not options[name].strip():
                    raise ConfigurationError("Email needs " + name)
                if any(c in options[name] for c in "\r\n\x00"):
                    raise ConfigurationError("Invalid email " + name)
            if not re.fullmatch(r"[A-Za-z0-9.-]+", options["smtp_host"]):
                raise ConfigurationError("SMTP host must be a hostname or IPv4 address")
            options["port"] = _bounded_number(options.get("port"), "SMTP port", 1, 65535)
            if options.get("security") not in ("tls", "starttls"):
                raise ConfigurationError("Email security must be tls or starttls")
            senders = normalize_recipients(options["from_address"])
            if len(senders) != 1:
                raise ConfigurationError("Exactly one sender address is required")
            options["from_address"] = senders[0]
            options["recipients"] = normalize_recipients(options.get("recipients"))
    return output


def summarize_markdown(markdown: str, limit: int = 3500) -> str:
    """Keep complete lines and Markdown links; omit oversized lines atomically."""
    if limit < 128:
        raise ConfigurationError("Summary byte limit must be at least 128")
    # Local/relative links do not work for mail or group recipients. Keep their label.
    markdown = re.sub(r"\[([^\]\n]*)\]\(([^)\n]+)\)",
        lambda match: match.group(0) if match.group(2).startswith(("https://", "http://"))
        else match.group(1) + "（本地资料）", markdown)
    marker = "\n\n（摘要已精简；完整报告保留在报告文件中。）"
    if len(markdown.encode("utf-8")) <= limit:
        return markdown
    available = limit - len(marker.encode("utf-8"))
    lines, used = [], 0
    for line in markdown.splitlines():
        encoded = (line + "\n").encode("utf-8")
        if used + len(encoded) <= available:
            lines.append(line)
            used += len(encoded)
        elif line.strip():
            # Do not cut links or multi-byte characters to fit a remaining fragment.
            continue
    if not lines:
        lines = ["报告已生成，正文较长，请查看完整报告。"]
    return "\n".join(lines).rstrip() + marker


def _valid_webhook(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or any(c in url for c in "\r\n\x00")):
            raise ValueError
        parsed.port
    except (ValueError, TypeError):
        raise ConfigurationError("Webhook must be a valid HTTPS URL without user credentials") from None
    return url


def build_dingtalk_url(webhook: str, secret: str, timestamp_ms: int) -> str:
    _valid_webhook(webhook)
    if not isinstance(secret, str) or not secret:
        raise ConfigurationError("DingTalk signing secret is empty")
    if type(timestamp_ms) is not int or timestamp_ms < 0:
        raise ConfigurationError("DingTalk timestamp must be a nonnegative integer")
    signing = (str(timestamp_ms) + "\n" + secret).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), signing, hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode("ascii")
    parsed = urllib.parse.urlsplit(webhook)
    # urlencode performs the sole URL-encoding step on the unencoded Base64 value.
    query = [(key, value) for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
             if key not in ("timestamp", "sign")]
    query.extend((("timestamp", str(timestamp_ms)), ("sign", signature)))
    return urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))


def _masked_target(target: str, channel: str) -> str:
    if channel == "email" and "@" in target:
        local, domain = target.rsplit("@", 1)
        return local[:1] + "***@" + domain
    if channel in ("wecom", "dingtalk"):
        return channel + ":configured-robot"
    return channel + ":configured" if channel != "codex" else "codex-host"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_transport(url: str, payload: dict[str, Any], timeout: int) -> HttpResponse:
    request = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    opener = urllib.request.build_opener(_NoRedirect(),
                urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(request, timeout=timeout) as response:
            return HttpResponse(response.status, response.read(65536), dict(response.headers))
    except urllib.error.HTTPError as error:
        return HttpResponse(error.code, error.read(65536), dict(error.headers))


def _smtp_transport(options: dict[str, Any], recipients: list[str], message: EmailMessage,
                    password: str) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    client = None
    stage = "connect"
    current = None
    try:
        context = ssl.create_default_context()
        if options["security"] == "tls":
            client = smtplib.SMTP_SSL(options["smtp_host"], options["port"],
                                     timeout=options["timeout"], context=context)
        else:
            client = smtplib.SMTP(options["smtp_host"], options["port"], timeout=options["timeout"])
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        stage = "login"
        client.login(options["username"], password)
        stage = "send"
        for recipient in recipients:
            current = recipient
            outgoing = copy.deepcopy(message)
            outgoing["To"] = recipient
            for attempt in range(1, options["max_attempts"] + 1):
                try:
                    refused = client.send_message(outgoing, from_addr=options["from_address"],
                                                  to_addrs=[recipient])
                    if refused:
                        code = int(refused[recipient][0])
                        result = {"status": "failed", "detail": "smtp_recipient_rejected", "code": code}
                    else:
                        result = {"status": "accepted", "detail": "smtp_server_accepted"}
                except smtplib.SMTPRecipientsRefused as error:
                    code = int(error.recipients.get(recipient, (550,))[0])
                    result = {"status": "failed", "detail": "smtp_recipient_rejected", "code": code}
                except smtplib.SMTPDataError as error:
                    result = {"status": "failed", "detail": "smtp_data_rejected", "code": error.smtp_code}
                result["attempts"] = attempt
                if result["status"] == "accepted" or not 400 <= result.get("code", 0) < 500:
                    break
                if attempt < options["max_attempts"]:
                    time.sleep(min(0.25 * 2 ** (attempt - 1), 1))
            results[recipient] = result
            current = None
    except smtplib.SMTPAuthenticationError:
        detail = "smtp_authentication_failed"
        for recipient in recipients:
            results.setdefault(recipient, {"status": "failed", "detail": detail, "attempts": 0})
    except (smtplib.SMTPException, OSError, ssl.SSLError):
        if stage == "send" and current is not None:
            results[current] = {"status": "unknown", "detail": "smtp_response_lost", "attempts": 1}
        for recipient in recipients:
            results.setdefault(recipient, {"status": "failed", "detail": "smtp_connection_or_tls_failed", "attempts": 0})
    finally:
        if client is not None:
            try:
                client.quit()
            except (smtplib.SMTPException, OSError):
                try:
                    client.close()
                except (smtplib.SMTPException, OSError):
                    pass
    return results


class _Ledger:
    """Reserve before transport so simultaneous runs cannot both send a target."""

    def __init__(self, path: Path, clock: Callable[[], float]):
        self.path, self.clock = path, clock

    @staticmethod
    def _recent_requests(entries, channel, target_hash, now):
        return sum(sum(timestamp > now - 60 for timestamp in entry.get("request_times", []))
                   for entry in entries.values()
                   if entry.get("channel") == channel and entry.get("target_hash") == target_hash)

    def _transaction(self, operation):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_suffix(self.path.suffix + ".lock")
        deadline = time.monotonic() + 3
        while True:
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise ConfigurationError("Delivery ledger is busy; retry after checking the active run")
                time.sleep(0.05)
        temporary = None
        try:
            if self.path.exists():
                try:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                    if data.get("version") != 1 or not isinstance(data.get("deliveries"), dict):
                        raise ValueError
                except (OSError, ValueError, AttributeError):
                    raise ConfigurationError("Delivery ledger is invalid; inspect it before sending") from None
            else:
                data = {"version": 1, "deliveries": {}}
            result = operation(data["deliveries"])
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".receipt-", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            return result
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
            lock.unlink(missing_ok=True)

    def reserve(self, key: str, channel: str, target_hash: str) -> dict[str, Any] | None:
        now = self.clock()
        def update(entries):
            existing = entries.get(key)
            if existing and existing.get("status") in ("accepted", "sent", "pending", "unknown"):
                if existing["status"] in ("pending", "unknown"):
                    return {"status": "unknown", "detail": "previous_delivery_needs_review", "attempts": 0}
                return {"status": "skipped", "detail": "already_delivered", "attempts": 0}
            if existing and existing.get("retry_at", 0) > now:
                return {"status": "failed", "detail": "rate_limit_cooldown", "retry_at": existing["retry_at"], "attempts": 0}
            if channel in ("wecom", "dingtalk"):
                recent = self._recent_requests(entries, channel, target_hash, now)
                if recent >= 20:
                    return {"status": "failed", "detail": "local_robot_rate_limit", "retry_at": now + 60, "attempts": 0}
            entries[key] = {"status": "pending", "channel": channel, "target_hash": target_hash,
                            "time": now, "attempts": 0,
                            "request_times": [stamp for stamp in (existing or {}).get("request_times", [])
                                              if stamp > now - 60]}
            return None
        return self._transaction(update)

    def robot_attempt(self, key: str) -> dict[str, Any] | None:
        """Count every actual HTTP attempt, including failures and retries."""
        now = self.clock()
        def update(entries):
            current = entries[key]
            recent = self._recent_requests(entries, current["channel"], current["target_hash"], now)
            if recent >= 20:
                return {"status": "failed", "detail": "local_robot_rate_limit",
                        "retry_at": now + 60, "attempts": current.get("attempts", 0)}
            current["attempts"] = current.get("attempts", 0) + 1
            current["time"] = now
            current.setdefault("request_times", []).append(now)
            return None
        return self._transaction(update)

    def finish(self, key: str, result: dict[str, Any]):
        def update(entries):
            entries[key].update(result)
            entries[key]["time"] = self.clock()
        self._transaction(update)


def _robot_result(transport, url: str, payload: dict[str, Any], config: dict[str, Any],
                  channel: str, clock, sleeper, before_attempt=None) -> dict[str, Any]:
    for attempt in range(1, config["max_attempts"] + 1):
        if before_attempt is not None:
            limited = before_attempt()
            if limited:
                return limited
        try:
            response = transport(url, payload, config["timeout"])
        except (OSError, socket.timeout, urllib.error.URLError, TimeoutError):
            return {"status": "unknown", "detail": "robot_response_lost", "attempts": attempt}
        except Exception:
            return {"status": "unknown", "detail": "robot_transport_unverifiable", "attempts": attempt}
        if response.status == 429:
            return {"status": "failed", "detail": "robot_rate_limited", "attempts": attempt,
                    "retry_at": clock() + (600 if channel == "dingtalk" else 60)}
        if 500 <= response.status < 600 and attempt < config["max_attempts"]:
            sleeper(min(0.25 * 2 ** (attempt - 1), 1))
            continue
        if not 200 <= response.status < 300:
            return {"status": "failed", "detail": "robot_http_error", "http_status": response.status, "attempts": attempt}
        try:
            body = json.loads(response.body)
            if not isinstance(body, dict) or type(body.get("errcode")) is not int:
                raise ValueError
        except (ValueError, TypeError, UnicodeError):
            return {"status": "unknown", "detail": "robot_unverifiable_response", "attempts": attempt}
        if body["errcode"] == 0:
            return {"status": "sent", "detail": "robot_platform_accepted", "attempts": attempt}
        message = str(body.get("errmsg", "")).lower()
        if any(word in message for word in ("rate limit", "frequency", "too frequent", "限流", "频率")):
            return {"status": "failed", "detail": "robot_rate_limited", "attempts": attempt,
                    "retry_at": clock() + (600 if channel == "dingtalk" else 60)}
        return {"status": "failed", "detail": "robot_business_error", "code": body["errcode"], "attempts": attempt}
    return {"status": "failed", "detail": "robot_retry_exhausted", "attempts": config["max_attempts"]}


def send_report(config: dict[str, Any] | None, report_path: str | Path, *,
                title: str | None = None, report_id: str | None = None,
                summary: str | None = None, state_path: str | Path | None = None,
                send: bool = False, secret_store=None, transports=None) -> dict[str, Any]:
    """Return safe JSON receipts. Only send=True can access secrets or transports.

    Inject transports={"email": callable, "webhook": callable, "clock": callable,
    "sleep": callable} for offline tests. The email callback receives normalized
    options, ready recipient addresses, an EmailMessage, and the SMTP credential.
    The webhook callback returns HttpResponse. No raw exception is returned.
    """
    if type(send) is not bool:
        raise ConfigurationError("send must be an explicit boolean")
    # Installer validation is strict; during a run one invalid channel must not
    # prevent the other selected channels from producing their receipts.
    config = validate_config(config, _validate_channels=False)
    path = Path(report_path).resolve()
    if not path.is_file() or path.suffix.lower() != ".md":
        raise ConfigurationError("Report must be an existing Markdown file")
    try:
        raw = path.read_bytes()
        markdown = raw.decode("utf-8-sig")
    except (OSError, UnicodeError):
        raise ConfigurationError("Report must be a readable UTF-8 Markdown file") from None
    if not markdown.strip():
        raise ConfigurationError("Report is empty")
    if summary is not None and not isinstance(summary, str):
        raise ConfigurationError("Summary must be text")
    title = title or next((line.lstrip("# ").strip() for line in markdown.splitlines() if line.strip()), "ESG report")
    if not isinstance(title, str) or any(c in title for c in "\r\n\x00"):
        raise ConfigurationError("Title must be one line")
    title = title[:160]
    report_id = report_id or path.stem
    if not isinstance(report_id, str) or not report_id or "\x00" in report_id:
        raise ConfigurationError("Invalid report identifier")
    summary = summarize_markdown(summary if summary is not None else markdown)
    version = hashlib.sha256(raw).hexdigest()
    environment = transports or {}
    clock = environment.get("clock", time.time)
    sleeper = environment.get("sleep", time.sleep)
    ledger = _Ledger(Path(state_path) if state_path is not None else user_data_root() / "state" / "deliveries.json", clock)
    results = []
    # Delay the protected store until an actual selected external channel needs it.
    store = secret_store

    def receipt(channel, target, result):
        return {"channel": channel, "target": _masked_target(target, channel),
                "target_id": hashlib.sha256(target.encode("utf-8")).hexdigest()[:16], **result}

    def key_for(channel, target):
        return hashlib.sha256((report_id + "\0" + version + "\0" + channel + "\0" + target).encode("utf-8")).hexdigest()

    for channel in config["channels"]:
        if channel == "codex":
            results.append(receipt(channel, "codex-host", {"status": "ready", "detail": "result_available_to_codex_host", "attempts": 0}))
            continue
        try:
            options = validate_config({**config, "channels": [channel]})[channel]
        except ConfigurationError:
            results.append(receipt(channel, channel + ":configured",
                {"status": "failed", "detail": "channel_configuration_error", "attempts": 0}))
            continue
        targets = options["recipients"] if channel == "email" else [channel + ":configured-robot"]
        if not send:
            results.extend(receipt(channel, target, {"status": "preview", "detail": "not_sent", "attempts": 0}) for target in targets)
            continue
        try:
            store = store or SecretStore()
            if channel == "email":
                password = store.get(options["password_ref"])
                ready = []
                for target in targets:
                    previous = ledger.reserve(key_for(channel, target), channel, hashlib.sha256(target.encode()).hexdigest())
                    if previous:
                        results.append(receipt(channel, target, previous))
                    else:
                        ready.append(target)
                if not ready:
                    continue
                message = EmailMessage()
                message["Subject"] = title
                message["From"] = options["from_address"]
                message.set_content(summary, charset="utf-8")
                message.add_attachment(markdown, subtype="markdown", charset="utf-8", filename=path.name)
                smtp_options = {**options, "timeout": config["timeout"], "max_attempts": config["max_attempts"]}
                try:
                    sent = environment.get("email", _smtp_transport)(smtp_options, ready, message, password)
                except Exception:
                    sent = {target: {"status": "unknown", "detail": "smtp_unverifiable_transport_result", "attempts": 1} for target in ready}
                for target in ready:
                    result = sent.get(target, {"status": "unknown", "detail": "smtp_missing_receipt", "attempts": 1})
                    if result.get("status") not in ("accepted", "failed", "unknown"):
                        result = {"status": "unknown", "detail": "smtp_invalid_receipt", "attempts": 1}
                    # Only known-safe fields leave transport code or enter the ledger.
                    result = {name: result[name] for name in ("status", "detail", "code", "attempts") if name in result}
                    ledger.finish(key_for(channel, target), result)
                    results.append(receipt(channel, target, result))
            else:
                webhook = _valid_webhook(store.get(options["webhook_ref"]))
                target = webhook
                if channel == "dingtalk":
                    webhook_to_send = build_dingtalk_url(webhook, store.get(options["secret_ref"]), int(clock() * 1000))
                    payload = {"msgtype": "markdown", "markdown": {"title": title, "text": summary}}
                else:
                    webhook_to_send = webhook
                    payload = {"msgtype": "markdown", "markdown": {"content": summary}}
                previous = ledger.reserve(key_for(channel, target), channel, hashlib.sha256(target.encode()).hexdigest())
                if previous:
                    results.append(receipt(channel, target, previous))
                    continue
                result = _robot_result(environment.get("webhook", _http_transport), webhook_to_send,
                                       payload, config, channel, clock, sleeper,
                                       before_attempt=lambda: ledger.robot_attempt(key_for(channel, target)))
                ledger.finish(key_for(channel, target), result)
                results.append(receipt(channel, target, result))
        except (SecretError, ConfigurationError):
            results.extend(receipt(channel, target, {"status": "failed", "detail": "channel_configuration_or_state_error", "attempts": 0}) for target in targets)
        except Exception:
            # No exception string is exposed: URLs and authentication details can be embedded.
            results.extend(receipt(channel, target, {"status": "unknown", "detail": "channel_result_unverifiable", "attempts": 0}) for target in targets)
    statuses = [result["status"] for result in results]
    if not send and not any(status in ("failed", "unknown") for status in statuses):
        overall = "preview"
    elif any(status in ("failed", "unknown") for status in statuses):
        overall = "partial_failure" if any(status in ("accepted", "sent", "ready", "skipped") for status in statuses) else ("unknown" if "unknown" in statuses else "failed")
    else:
        overall = "success"
    return {"preview": not send, "overall_status": overall, "report_id": report_id,
            "report_version": version, "report_path": str(path), "title": title,
            "summary": summary, "results": results,
            "generated_at": datetime.fromtimestamp(clock(), timezone.utc).isoformat()}
