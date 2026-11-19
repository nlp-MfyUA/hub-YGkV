"""Embedding client for the existing rag-models service."""
import asyncio
import logging
import math
import struct

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def _embed_batch(client: httpx.AsyncClient, texts: list[str]) -> list[list[float]]:
    payload: dict = {"input": texts}
    if settings.embedding_model:
        payload["model"] = settings.embedding_model
    headers = {}
    if settings.model_service_api_key:
        headers["Authorization"] = f"Bearer {settings.model_service_api_key}"
    url = f"{settings.model_service_url.rstrip('/')}/v1/embeddings"
    resp = await client.post(url, json=payload, headers=headers)
    if resp.status_code == 422 and "model" in payload:
        payload.pop("model", None)
        resp = await client.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json().get("data") or []
    data.sort(key=lambda x: x.get("index", 0))
    vectors = [item["embedding"] for item in data]
    if len(vectors) != len(texts):
        raise RuntimeError(f"embedding 返回数量不符: {len(vectors)} != {len(texts)}")
    return vectors


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        out: list[list[float]] = []
        batch_size = max(1, settings.embedding_batch_size)
        for i in range(0, len(texts), batch_size):
            out.extend(await _embed_batch(client, texts[i:i + batch_size]))
        return out


def pack_vector(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_vector(data: bytes | None) -> list[float]:
    if not data:
        return []
    return list(struct.unpack(f"<{len(data) // 4}f", data))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
