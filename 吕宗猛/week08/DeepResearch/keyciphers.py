"""AES-GCM 加密模型 API Key：密钥来自 .env 的 ENCRYPTION_KEY。

密文落库格式：base64(nonce 12B + ciphertext)，解密时切出前 12 字节作 nonce。
"""
import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_master_key: bytes | None = None


def _key() -> bytes:
    global _master_key
    if _master_key is None:
        env_key = os.environ.get("ENCRYPTION_KEY", "")
        if not env_key:
            raise RuntimeError("缺少 ENCRYPTION_KEY，请在 .env 中配置（32 字节随机串）")
        _master_key = hashlib.sha256(env_key.encode()).digest()
    return _master_key


def encrypt(plaintext: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt(token: str) -> str:
    raw = base64.b64decode(token)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(_key()).decrypt(nonce, ct, None).decode()


def mask(key: str) -> str:
    """脱敏展示：前缀 3 位 + **** + 末 3 位；过短只留末 3 位。"""
    if len(key) <= 6:
        return "****" + key[-3:]
    return key[:3] + "****" + key[-3:]
