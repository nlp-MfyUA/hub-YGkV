"""Magpie OpenAI-compatible multimodal chat client and RAG prompt builder."""
import base64
import json
import logging
import mimetypes
import re
from pathlib import Path

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
IMG_MARKER_RE = re.compile(r"\[\[img:(\d+)\]\]")


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _image_part(path: Path) -> dict:
    return {"type": "image_url", "image_url": {"url": _data_uri(path)}}


async def call_magpie(messages: list[dict], max_tokens: int | None = None) -> str:
    headers = {"Content-Type": "application/json"}
    if settings.magpie_api_key:
        headers["Authorization"] = f"Bearer {settings.magpie_api_key}"
    payload = {
        "model": settings.magpie_model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens or settings.llm_max_tokens,
    }
    url = f"{settings.magpie_base_url.rstrip('/')}/chat/completions"
    async with httpx.AsyncClient(timeout=settings.llm_timeout, trust_env=False) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"Magpie HTTP {resp.status_code}: {resp.text[:1000]}")
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"Magpie 返回无 choices: {json.dumps(data, ensure_ascii=False)[:800]}")
        return choices[0]["message"].get("content") or ""


def build_messages(
    question: str,
    chunks: list,
    history: list[dict],
    user_image_path: Path | None = None,
    include_images: bool = True,
) -> list[dict]:
    system = (
        "你是多模态 RAG 知识库助手。你只能依据下面提供的资料回答，不得编造资料之外的事实。"
        "资料由文字块和对应的图片组成；请先结合图片与周围文字理解内容，再回答问题。"
        "回答使用中文 Markdown，结构清晰。"
        "如果回答中需要展示资料里的某张图片，请在对应位置写 [[img:图片ID]]，"
        "图片ID只能使用资料中标注过的ID，不要编造。"
    )
    messages: list[dict] = [{"role": "system", "content": system}]
    for item in history:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})

    parts: list[dict] = []
    if chunks:
        for i, chunk in enumerate(chunks, start=1):
            parts.append({
                "type": "text",
                "text": (
                    f"【资料{i}｜文档：{chunk.doc_name}｜块：{chunk.chunk_index}｜相关度：{chunk.score:.3f}】\n"
                    f"{chunk.content}"
                ),
            })
            if include_images:
                for image in chunk.images:
                    parts.append({
                        "type": "text",
                        "text": f"【资料{i} 图片ID={image['id']}｜{image['file_name']}】",
                    })
                    parts.append(_image_part(Path(image["path"])))
    else:
        parts.append({"type": "text", "text": "【资料】未检索到可用资料，请明确告知用户知识库中没有相关内容。"})

    parts.append({"type": "text", "text": f"【用户问题】\n{question or '请描述这张图片并回答我。'}"})
    if user_image_path:
        parts.append({"type": "text", "text": "【用户上传图片】"})
        parts.append(_image_part(user_image_path))
    messages.append({"role": "user", "content": parts})
    return messages


async def generate_session_title(transcript: str) -> str:
    """Ask the chat model for a short Chinese title for the current conversation."""
    prompt = [
        {"role": "system", "content": "你是会话标题生成器。只输出一个不超过20个汉字的标题，不要标点、引号、解释或前缀。"},
        {"role": "user", "content": transcript[:3000]},
    ]
    text = await call_magpie(prompt, max_tokens=64)
    title = (text or "").strip().splitlines()[0].strip("# \t\"'“”‘’：: ")
    title = re.sub(r"^(会话标题|标题)[：:]\s*", "", title).strip()
    return title[:40]


def render_answer(answer: str, image_map: dict[int, dict], fallback_images: list[dict]) -> tuple[str, list[int]]:
    used: list[int] = []

    def repl(match: re.Match) -> str:
        image_id = int(match.group(1))
        image = image_map.get(image_id)
        if not image:
            return ""
        if image_id not in used:
            used.append(image_id)
        return f"![图片]({image['url']})"

    rendered = IMG_MARKER_RE.sub(repl, answer).strip()
    if not used and "/api/documents/" in rendered:
        for image_id, image in image_map.items():
            if image["url"] in rendered and image_id not in used:
                used.append(image_id)
        return rendered, used
    if not used and fallback_images:
        gallery = []
        for image in fallback_images[:4]:
            gallery.append(f"![图片]({image['url']})")
            if image["id"] not in used:
                used.append(image["id"])
        rendered += "\n\n**相关图片**\n" + "\n\n".join(gallery)
    return rendered, used
