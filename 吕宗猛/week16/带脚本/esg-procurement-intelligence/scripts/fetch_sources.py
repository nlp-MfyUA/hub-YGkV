#!/usr/bin/env python3
"""Save public source bytes, readable text and retrieval metadata for research."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


class TextExtractor(HTMLParser):
    BLOCKS = {"p", "div", "section", "article", "header", "footer", "h1", "h2", "h3", "h4",
              "h5", "h6", "li", "tr", "br", "hr", "table", "ul", "ol", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts: list[str] = []
        self.tables: list[dict] = []

    def append(self, text):
        if self.tables:
            cell = self.tables[-1].get("cell")
            if cell is not None:
                cell["parts"].append(text)
        else:
            self.parts.append(text)

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if self.skip:
            return
        if tag == "table":
            self.tables.append({"rows": [], "row": None, "cell": None})
        elif self.tables and tag == "tr":
            self.tables[-1]["row"] = []
        elif self.tables and tag in ("td", "th"):
            attributes = dict(attrs)
            def span(name):
                try:
                    return min(100, max(1, int(attributes.get(name, "1"))))
                except (TypeError, ValueError):
                    return 1
            self.tables[-1]["cell"] = {"parts": [], "colspan": span("colspan"),
                                        "rowspan": span("rowspan")}
        elif tag in self.BLOCKS:
            self.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
        if self.skip:
            return
        if self.tables and tag in ("td", "th"):
            table = self.tables[-1]
            if table["cell"] is not None:
                if table["row"] is None:
                    table["row"] = []
                table["row"].append(table["cell"])
                table["cell"] = None
        elif self.tables and tag == "tr":
            table = self.tables[-1]
            if table["row"] is not None:
                table["rows"].append(table["row"])
                table["row"] = None
        elif self.tables and tag == "table":
            table = self.tables.pop()
            self.append("\n" + self.render_table(table["rows"]) + "\n")
        elif tag in self.BLOCKS:
            self.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.append(data)

    @staticmethod
    def render_table(rows):
        """Preserve cell boundaries; never repeat a merged monetary value."""
        grid = {}
        merged = False
        for row_number, row in enumerate(rows):
            column = 0
            for cell in row:
                while (row_number, column) in grid:
                    column += 1
                value = re.sub(r"\s+", " ", "".join(cell["parts"])).strip()
                grid[row_number, column] = value
                for offset_row in range(cell["rowspan"]):
                    for offset_column in range(cell["colspan"]):
                        if offset_row or offset_column:
                            merged = True
                            grid[row_number + offset_row, column + offset_column] = (
                                f"[merged: row {row_number + 1}, column {column + 1}]")
                column += cell["colspan"]
        if not grid:
            return ""
        width = max(column for _, column in grid) + 1
        height = max(row for row, _ in grid) + 1
        lines = ["[HTML table; columns separated by tabs" +
                 ("; merged markers refer to the original cell, not extra values]" if merged else "]")]
        lines.extend("\t".join(grid.get((row, column), "") for column in range(width))
                     for row in range(height))
        lines.append("[/HTML table]")
        return "\n".join(lines)

    def text(self) -> str:
        lines = [re.sub(r"[ \u00a0]+", " ", line).strip(" \r")
                 for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line.strip()) + "\n" if any(line.strip() for line in lines) else ""


def decode_page(raw: bytes, content_type: str = "") -> str:
    return decode_page_with_encoding(raw, content_type)[0]


def decode_page_with_encoding(raw: bytes, content_type: str = "") -> tuple[str, str]:
    match = re.search(r"charset\s*=\s*[\"']?([\w.-]+)", content_type, re.I)
    encodings = [match.group(1)] if match else []
    meta = re.search(br"charset\s*=\s*[\"']?([\w.-]+)", raw[:4096], re.I)
    if meta:
        encodings.append(meta.group(1).decode("ascii"))
    encodings.extend(("utf-8-sig", "gb18030"))
    for encoding in dict.fromkeys(encodings):
        try:
            return raw.decode(encoding), encoding
        except (LookupError, UnicodeError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8_with_replacement"


def unreadable_html_reason(html: str, text: str, final_url: str = "") -> str | None:
    title = re.search(r"<title\b[^>]*>(.*?)</title\s*>", html, re.I | re.S)
    heading = re.sub(r"<[^>]*>", "", title.group(1)) if title else ""
    if re.search(r"验证码|人机验证|安全验证|访问受限|访问拒绝|access denied|forbidden|security verification|just a moment", heading, re.I):
        return "access_restricted_or_captcha"
    if re.search(r"(?:qcaptcha|captcha)\.", urllib.parse.urlsplit(final_url).hostname or "", re.I):
        return "access_restricted_or_captcha"
    if len(text) < 1500 and re.search(r"请完成验证|请输入验证码|请拖动滑块|verify you are human|checking your browser|enable javascript and cookies|访问过于频繁|无权访问|您的访问被阻止", text, re.I):
        return "access_restricted_or_captcha"
    if re.search(r"<form\b[^>]*(?:challenge-form|captcha)", html, re.I):
        return "access_restricted_or_captcha"
    if re.search(r"登录|sign in|log in", heading, re.I) and len(text) < 1500:
        return "login_required"
    if (text.strip() in ("", heading.strip()) and re.search(r"<script\b", html, re.I)) or (
            len(text) < 500 and re.search(r"enablejs|please enable javascript|请启用\s*javascript|需要启用\s*javascript", html, re.I)):
        return "javascript_required"
    return None if text.strip() else "no_readable_text"


def extract_pdf(path: Path) -> tuple[str | None, str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, "pypdf_unavailable_use_bundled_python"
    try:
        reader = PdfReader(str(path))
        page_texts = [(page.extract_text() or "") for page in reader.pages]
        if not any(text.strip() for text in page_texts):
            return None, "no_text_layer"
        pages = [f"\n[PDF page {number}]\n" + (text if text.strip() else "[No extractable text on this page]")
                 for number, text in enumerate(page_texts, 1)]
        return "\n".join(pages), ("partial_text_layer" if any(not text.strip() for text in page_texts)
                                   else "text_extracted")
    except Exception:
        return None, "pdf_extraction_failed"


def fetch_one(job: dict, directory: Path, *, timeout: int = 20,
              max_bytes: int = 20_000_000, proxy: str | None = None) -> dict:
    url = job.get("url")
    try:
        parsed_url = urllib.parse.urlsplit(url) if isinstance(url, str) else None
    except ValueError:
        parsed_url = None
    if parsed_url is None or parsed_url.scheme not in ("http", "https") or not parsed_url.hostname:
        return {"id": job.get("id"), "status": "invalid_url"}
    source_id = str(job.get("id") or job.get("source_id") or hashlib.sha256(url.encode()).hexdigest()[:12])
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", source_id):
        return {"id": source_id, "url": url, "status": "invalid_source_id"}
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    result = {"id": source_id, "url": url,
              "retrieved_at": datetime.now(timezone.utc).isoformat(), "readable": False}
    try:
        if timeout <= 0 or max_bytes <= 0:
            raise ValueError("Invalid retrieval bounds")
        # A failed refresh must not leave an old text file looking current.
        (directory / (source_id + ".txt")).unlink(missing_ok=True)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy})) if proxy else urllib.request.build_opener()
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 CodexESGResearch/1.0",
                                                       "Accept": "text/html,application/pdf,text/plain,*/*"})
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error  # Preserve the response body and actual HTTP status.
        with response:
            content_type = response.headers.get("Content-Type", "")
            result.update(final_url=response.geturl(), http_status=response.status,
                          content_type=content_type)
            content_length = response.headers.get("Content-Length", "")
            if content_length.isdigit():
                result["declared_bytes"] = int(content_length)
            raw = response.read(max_bytes + 1)
        result.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        if len(raw) > max_bytes:
            path = directory / (source_id + ".partial.bin")
            path.write_bytes(raw)
            result.update(status="source_too_large", extraction="not_attempted",
                          snapshot=str(path), snapshot_complete=False,
                          sha256_scope="stored_prefix", max_bytes=max_bytes)
        else:
            mime = content_type.partition(";")[0].strip().lower()
            is_pdf = raw.lstrip().startswith(b"%PDF-") or mime == "application/pdf"
            supported_text = (mime.startswith("text/") or mime in ("", "application/xhtml+xml")
                              or raw.lstrip().startswith((b"<html", b"<!DOCTYPE", b"<!doctype")))
            suffix = ".pdf" if is_pdf else (".html" if supported_text else ".bin")
            path = directory / (source_id + suffix)
            path.write_bytes(raw)
            result.update(snapshot=str(path), snapshot_complete=True, sha256_scope="complete_source")
            if is_pdf:
                text, extraction = extract_pdf(path)
            elif supported_text:
                html, encoding = decode_page_with_encoding(raw, content_type)
                result["encoding"] = encoding
                if mime == "text/plain":
                    text, extraction = html, "plain_text_extracted" if html.strip() else "no_readable_text"
                else:
                    parser = TextExtractor()
                    parser.feed(html)
                    parser.close()
                    text = parser.text()
                    extraction = unreadable_html_reason(html, text, result["final_url"]) or "html_text_extracted"
            else:
                text, extraction = None, "unsupported_content_type"
            result["extraction"] = extraction
            result["verification"] = "researcher_must_check_original_dates_scope_and_excerpt"
            if result["http_status"] >= 400:
                result["status"] = "access_restricted" if result["http_status"] in (401, 403, 429) else "http_error"
            elif extraction in ("access_restricted_or_captcha", "login_required"):
                result["status"] = "access_restricted"
            elif extraction in ("text_extracted", "partial_text_layer", "html_text_extracted", "plain_text_extracted"):
                text_path = directory / (source_id + ".txt")
                text_path.write_text(text, encoding="utf-8")
                result.update(status="retrieved", readable=True, text_path=str(text_path), text_chars=len(text))
                if extraction == "partial_text_layer":
                    result["warning"] = "Some PDF pages have no text layer; omitted page content requires visual review or OCR."
            else:
                result["status"] = "unreadable"
    except Exception:
        result.update(status="retrieval_failed")
    (directory / (source_id + ".metadata.json")).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="JSON array of {id,url}, or object containing sources")
    parser.add_argument("--url", help="Fetch one public source")
    parser.add_argument("--id", default="source")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--max-bytes", type=int, default=20_000_000, help="Maximum source download size; oversized snapshots are partial")
    parser.add_argument("--proxy", help="Explicit HTTP(S) proxy, if required by your environment")
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.workers <= 4 or not 1 <= args.timeout <= 30 or args.max_bytes < 1:
            raise ValueError
        if args.url:
            jobs = [{"id": args.id, "url": args.url}]
        elif args.input:
            value = json.loads(args.input.read_text(encoding="utf-8-sig"))
            jobs = value.get("sources", []) if isinstance(value, dict) else value
            if not isinstance(jobs, list) or not all(isinstance(job, dict) for job in jobs):
                raise ValueError
        else:
            parser.error("Provide --input or --url")
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(lambda job: fetch_one(job, args.output_dir,
                                  timeout=args.timeout, max_bytes=args.max_bytes, proxy=args.proxy), jobs))
        manifest = args.output_dir / "retrieval-manifest.json"
        args.output_dir.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"sources": len(results),
                          "retrieved": sum(row.get("readable", False) for row in results),
                          "manifest": str(manifest.resolve())}, ensure_ascii=False))
        return 0 if all(row["status"] == "retrieved" for row in results) else 1
    except (OSError, ValueError, TypeError):
        print("Invalid source input, options or output directory", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
