"""Language-model provider for shift reports (Module 3).

Only the Python standard library is used (``urllib``), so no new dependency.
Security properties:
* the API key is sent in the ``x-goog-api-key`` header, never in the URL, and
  never logged or returned to clients;
* responses are size-capped and only metadata (status, latency, token counts)
  is logged — never prompt or response text;
* every failure becomes a :class:`ProviderError` with a safe public message.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_RESPONSE_BYTES = 1_000_000
# Newer Gemini models "think" before answering and those thinking tokens count
# against this limit, so it leaves room for both thinking and the JSON report.
MAX_OUTPUT_TOKENS = 8192
READ_CHUNK_BYTES = 65_536
THINKING_LEVELS = ("minimal", "low", "medium", "high")
MAX_ERROR_BODY_BYTES = 65_536
# One retry, after a short pause, for transient Gemini server errors (overloaded model).
# Only when the failed attempt was quick, so a retry never doubles a long wait.
RETRYABLE_STATUSES = frozenset({500, 502, 503})
RETRY_DELAY_SECONDS = 2.0
RETRY_ONLY_IF_FAILED_WITHIN_SECONDS = 10.0
# Google error bodies carry an enum such as "NOT_FOUND" or "UNAVAILABLE". Only a value
# matching this pattern is kept; the free-text message in the body is never used.
_GOOGLE_STATUS = re.compile(r"^[A-Z_]{1,40}$")


class ProviderError(Exception):
    """A provider call failed. ``message`` is safe to show to API clients."""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = False


def not_configured() -> ProviderError:
    return ProviderError(
        "ai_not_configured",
        "AI report generation is not configured on the server.",
        503,
    )


def timeout_error() -> ProviderError:
    return ProviderError("ai_timeout", "The AI provider did not respond in time.", 504)


def rate_limited() -> ProviderError:
    return ProviderError(
        "ai_rate_limited", "The AI provider's rate limit was reached. Try again later.", 429
    )


def auth_failed() -> ProviderError:
    return ProviderError(
        "ai_auth_failed", "The AI provider rejected the server's credentials.", 502
    )


def _suffix(http_status: int | None, google_status: str | None) -> str:
    parts = [f"HTTP {http_status}"] if http_status else []
    if google_status:
        parts.append(google_status)
    return f" ({', '.join(parts)})" if parts else ""


def unavailable(http_status: int | None = None, google_status: str | None = None) -> ProviderError:
    return ProviderError(
        "ai_unavailable",
        f"The AI provider is currently unavailable{_suffix(http_status, google_status)}.",
        502,
    )


def model_not_found(model: str, google_status: str | None = None) -> ProviderError:
    return ProviderError(
        "ai_model_not_found",
        f"The AI model '{model}' was not found or does not support content generation"
        f"{_suffix(404, google_status)}. Check GEMINI_MODEL in the server configuration.",
        502,
    )


def provider_server_error(http_status: int, google_status: str | None = None) -> ProviderError:
    return ProviderError(
        "ai_provider_error",
        f"The AI provider had a server error{_suffix(http_status, google_status)}. "
        "This is usually temporary (for example an overloaded model); try again later "
        "or use a different GEMINI_MODEL.",
        502,
    )


def network_error(reason: object = None) -> ProviderError:
    # Only the exception class name is exposed (e.g. SSLCertVerificationError), never its text.
    kind = f" ({type(reason).__name__})" if isinstance(reason, BaseException) else ""
    return ProviderError(
        "ai_network_error",
        f"The server could not connect to the AI provider{kind}. "
        "Check the server's internet access, proxy and SSL certificates.",
        502,
    )


def bad_response(detail: str = "") -> ProviderError:
    message = "The AI provider returned an unusable response."
    return ProviderError("ai_bad_response", f"{message} {detail}".strip(), 502)


def invalid_output(detail: str = "") -> ProviderError:
    message = "The AI output did not match the required report structure."
    return ProviderError("ai_invalid_output", f"{message} {detail}".strip(), 502)


@dataclass(frozen=True)
class Prompt:
    system: str
    user: str


@dataclass(frozen=True)
class ProviderResult:
    text: str
    provider: str
    model: str


class ReportProvider(Protocol):
    name: str
    model: str

    def generate(self, prompt: Prompt) -> ProviderResult: ...


class GeminiProvider:
    """Google Gemini ``generateContent`` over HTTPS, JSON output mode."""

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float,
        thinking_level: str | None = None,
    ) -> None:
        if not api_key.strip():
            raise not_configured()
        if thinking_level and thinking_level not in THINKING_LEVELS:
            raise ValueError(f"thinking_level must be one of {THINKING_LEVELS}")
        self._api_key = api_key.strip()
        self.model = model
        self._timeout = timeout_seconds
        self._thinking_level = thinking_level or None
        self._sleep = time.sleep  # replaced in tests
        self._clock = time.monotonic  # replaced in tests

    def __repr__(self) -> str:  # never include the key
        return f"GeminiProvider(model={self.model!r})"

    def _request(self, prompt: Prompt) -> urllib.request.Request:
        generation_config: dict[str, Any] = {
            "temperature": 0.2,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "responseMimeType": "application/json",
        }
        if self._thinking_level:
            # Less thinking = much faster answers; the report task is simple summarising.
            generation_config["thinkingConfig"] = {"thinkingLevel": self._thinking_level}
        body = {
            "systemInstruction": {"parts": [{"text": prompt.system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt.user}]}],
            "generationConfig": generation_config,
        }
        return urllib.request.Request(  # noqa: S310 - fixed https endpoint
            GEMINI_ENDPOINT.format(model=self.model),
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
            method="POST",
        )

    def generate(self, prompt: Prompt, *, timeout_seconds: float | None = None) -> ProviderResult:
        """``timeout_seconds`` overrides the configured limit for this call only
        (the workflow agent passes what is left of its overall budget)."""
        timeout = min(self._timeout, timeout_seconds) if timeout_seconds else self._timeout
        started = self._clock()
        try:
            raw = self._call(prompt, timeout)
        except ProviderError as exc:
            quick = self._clock() - started <= RETRY_ONLY_IF_FAILED_WITHIN_SECONDS
            if not (exc.retryable and quick):
                raise
            self._sleep(RETRY_DELAY_SECONDS)
            raw = self._call(prompt, timeout)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise bad_response("The response was too large.")
        return ProviderResult(text=_extract_text(raw), provider=self.name, model=self.model)

    def _call(self, prompt: Prompt, timeout: float) -> bytes:
        started = time.monotonic()
        deadline = self._clock() + timeout
        status: int | None = None
        google_status: str | None = None
        error_code: str | None = None
        try:
            with urllib.request.urlopen(  # noqa: S310 - fixed https endpoint
                self._request(prompt), timeout=timeout
            ) as response:
                status = response.status
                return self._read_body(response, deadline)
        except urllib.error.HTTPError as exc:
            status = exc.code
            google_status = _google_status(exc)
            error = _http_error(exc.code, self.model, google_status)
            error_code = error.code
            raise error from None
        except TimeoutError:
            error_code = "ai_timeout"
            raise timeout_error() from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                error_code = "ai_timeout"
                raise timeout_error() from None
            error_code = "ai_network_error"
            raise network_error(exc.reason) from None
        except OSError as exc:
            error_code = "ai_network_error"
            raise network_error(exc) from None
        finally:
            logger.info(
                "ai provider call model=%s http_status=%s google_status=%s error_code=%s",
                self.model,
                status,
                google_status,
                error_code,
                extra={
                    "provider": self.name,
                    "model": self.model,
                    "http_status": status,
                    "google_status": google_status,
                    "error_code": error_code,
                    "latency_ms": round((time.monotonic() - started) * 1000),
                },
            )


    def _read_body(self, response: Any, deadline: float) -> bytes:
        """Read the body, but give up when the attempt's overall deadline passes.

        The socket timeout only limits each single wait, so a slowly trickling
        response could otherwise keep the request open far longer than configured.
        """
        read = getattr(response, "read1", None) or response.read
        chunks: list[bytes] = []
        size = 0
        while size <= MAX_RESPONSE_BYTES:
            if self._clock() > deadline:
                raise TimeoutError
            chunk = read(min(READ_CHUNK_BYTES, MAX_RESPONSE_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        return b"".join(chunks)


def _google_status(exc: urllib.error.HTTPError) -> str | None:
    """The ``error.status`` enum from a Google error body, or None. Never the message."""
    try:
        payload = json.loads(exc.read(MAX_ERROR_BODY_BYTES).decode("utf-8"))
    except Exception:  # noqa: BLE001 - any unreadable body just means "unknown"
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    value = error.get("status") if isinstance(error, dict) else None
    return value if isinstance(value, str) and _GOOGLE_STATUS.match(value) else None


def _http_error(code: int, model: str, google_status: str | None = None) -> ProviderError:
    if code == 429:
        return rate_limited()
    if code in (401, 403):
        return auth_failed()
    if code == 400:
        # Gemini reports an invalid API key as 400 too; the body's message is never echoed.
        return ProviderError(
            "ai_request_rejected",
            f"The AI provider rejected the request{_suffix(code, google_status)}. "
            "Check the API key and model name.",
            502,
        )
    if code == 404:
        return model_not_found(model, google_status)
    if code in (408, 504):
        return timeout_error()
    if code >= 500:
        error = provider_server_error(code, google_status)
        error.retryable = code in RETRYABLE_STATUSES
        return error
    return unavailable(code, google_status)


def _extract_text(raw: bytes) -> str:
    try:
        payload: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise bad_response("The response was not JSON.") from None
    if not isinstance(payload, dict):
        raise bad_response()

    usage = payload.get("usageMetadata")
    if isinstance(usage, dict):
        logger.info(
            "ai provider usage",
            extra={
                "prompt_tokens": usage.get("promptTokenCount"),
                "output_tokens": usage.get("candidatesTokenCount"),
            },
        )

    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        blocked = (payload.get("promptFeedback") or {}).get("blockReason")
        raise bad_response("The request was blocked." if blocked else "No content was returned.")
    candidate = candidates[0] if isinstance(candidates[0], dict) else {}
    finish = candidate.get("finishReason")
    if finish not in (None, "STOP"):
        detail = "The output was cut off." if finish == "MAX_TOKENS" else "Generation stopped."
        raise bad_response(detail)
    parts = (candidate.get("content") or {}).get("parts")
    if not isinstance(parts, list):
        raise bad_response("No content was returned.")
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    if not text.strip():
        raise bad_response("No content was returned.")
    return text