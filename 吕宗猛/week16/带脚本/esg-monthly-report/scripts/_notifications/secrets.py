"""Current-user protected secrets; plaintext is never written to disk."""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


class SecretError(ValueError):
    """A safe-to-display secret configuration error."""


def user_data_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "CodexESG" if base else Path.home() / ".config" / "CodexESG"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise SecretError("DPAPI requires Windows; use an env:NAME reference on this platform")
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    incoming = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = _Blob()
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                         ctypes.POINTER(_Blob)]
    function.restype = wintypes.BOOL
    # CRYPTPROTECT_UI_FORBIDDEN; current-user protection is the default scope.
    if not function(ctypes.byref(incoming), None, None, None, None, 1,
                    ctypes.byref(outgoing)):
        raise SecretError("Current-user protected secret could not be read or written")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        kernel.LocalFree(outgoing.pbData)


class SecretStore:
    """Store ciphertext outside Git; resolve dpapi:NAME and env:NAME references."""

    def __init__(self, root: str | Path | None = None):
        self.root = (Path(root) if root is not None else user_data_root() / "secrets").resolve()
        if any((parent / ".git").exists() for parent in (self.root, *self.root.parents)):
            raise SecretError("Secret storage must be outside a Git checkout")

    @staticmethod
    def _name(name: str) -> str:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,159}", name):
            raise SecretError("Secret name must contain only letters, digits, and ._/:\u002d")
        return name

    def _path(self, name: str) -> Path:
        name = self._name(name)
        return self.root / (hashlib.sha256(name.encode("utf-8")).hexdigest() + ".json")

    def set(self, name: str, value: str) -> str:
        self._name(name)
        if not isinstance(value, str) or not value:
            raise SecretError("A nonempty secret is required")
        protected = _dpapi(value.encode("utf-8"), decrypt=False)
        payload = json.dumps({"version": 1, "ciphertext": base64.b64encode(protected).decode("ascii")})
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.root,
                                             prefix=".secret-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path(name))
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return "dpapi:" + name

    def get(self, reference: str) -> str:
        validate_reference(reference)
        scheme, name = reference.split(":", 1)
        if scheme == "env":
            value = os.environ.get(name)
            if not value:
                raise SecretError("Configured environment secret is unavailable")
            return value
        try:
            payload = json.loads(self._path(name).read_text(encoding="utf-8"))
            if payload.get("version") != 1:
                raise SecretError("Unsupported protected secret format")
            ciphertext = base64.b64decode(payload["ciphertext"], validate=True)
            value = _dpapi(ciphertext, decrypt=True).decode("utf-8")
        except SecretError:
            raise
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            raise SecretError("Configured protected secret is unavailable or invalid") from None
        if not value:
            raise SecretError("Configured protected secret is empty")
        return value


def validate_reference(reference: str) -> str:
    if not isinstance(reference, str) or ":" not in reference:
        raise SecretError("Secret reference must be env:NAME or dpapi:NAME")
    scheme, name = reference.split(":", 1)
    if scheme == "env":
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise SecretError("Invalid environment secret name")
    elif scheme == "dpapi":
        SecretStore._name(name)
    else:
        raise SecretError("Secret reference must be env:NAME or dpapi:NAME")
    return reference
