"""错误层级：每个错误码绑定 HTTP 状态码与中文 detail（功能设计文档 §5）。

main.py 只需注册一个 ApiError 异常处理器，即可产出统一错误响应：
{"request_id": ..., "error_code": ..., "detail": ...}
"""
from __future__ import annotations


class ApiError(Exception):
    """API 层统一异常基类。

    retryable=True 表示调用方可在预算内重试（仅网络错误与 5xx，见 F-07）。
    """

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, detail: str, *, retryable: bool = False):
        super().__init__(detail)
        self.detail = detail
        self.retryable = retryable


class UnsupportedImageTypeError(ApiError):
    status_code, error_code = 422, "unsupported_image_type"


class ImageTooLargeError(ApiError):
    status_code, error_code = 413, "image_too_large"


class ImageTooSmallError(ApiError):
    status_code, error_code = 422, "image_too_small"


class ModelTimeoutError(ApiError):
    status_code, error_code = 504, "model_timeout"


class ModelUpstreamError(ApiError):
    status_code, error_code = 502, "model_upstream_error"


class ModelOutputUnparseableError(ApiError):
    status_code, error_code = 502, "model_output_unparseable"


class InvalidEnumError(ApiError):
    status_code, error_code = 502, "invalid_enum"


class ProviderNotConfiguredError(ApiError):
    status_code, error_code = 503, "provider_not_configured"


class UnauthorizedError(ApiError):
    status_code, error_code = 401, "unauthorized"
