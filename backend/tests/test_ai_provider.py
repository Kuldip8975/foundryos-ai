"""Gemini provider and AI output parsing (Module 3). ``urlopen`` is mocked: no network."""

from __future__ import annotations

import io
import json
import ssl
import urllib.error
from unittest import mock

import pytest

from app.services import ai_provider
from app.services.ai_provider import GeminiProvider, Prompt, ProviderError
from app.services.shift_reports import build_prompt, parse_report

PROMPT = Prompt(system="system text", user="user text")
METRICS = {
    "production_date": "2026-01-10", "shift": "A", "window_start": None, "window_end": None,
    "production": {"actual_quantity": 95, "target_achievement": 0.95},
    "quality": {"defect_rate": None},
    "limitations": ["No shift time window was given."],
}


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status
        self.offset = 0

    def read(self, limit: int) -> bytes:
        chunk = self.body[self.offset : self.offset + limit]
        self.offset += len(chunk)
        return chunk

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> bool:
        return False


def gemini_body(text: str, finish: str = "STOP") -> bytes:
    return json.dumps(
        {"candidates": [{"finishReason": finish, "content": {"parts": [{"text": text}]}}]}
    ).encode()


def http_error(code: int, body: bytes = b"sensitive body") -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body))


def google_error(code: int, status: str, message: str = "sensitive message") -> bytes:
    return json.dumps({"error": {"code": code, "status": status, "message": message}}).encode()


@pytest.fixture
def provider() -> GeminiProvider:
    created = GeminiProvider(api_key="secret-key-123", model="gemini-2.5-flash", timeout_seconds=5)
    created._sleep = lambda _seconds: None  # no real waiting before a retry
    return created


class FakeClock:
    """Time that only moves when a test says so."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_key_is_sent_in_header_not_url(provider: GeminiProvider) -> None:
    with mock.patch("urllib.request.urlopen", return_value=FakeResponse(gemini_body("{}"))) as call:
        result = provider.generate(PROMPT)
    request = call.call_args.args[0]
    assert "secret-key-123" not in request.full_url
    assert request.get_header("X-goog-api-key") == "secret-key-123"
    assert call.call_args.kwargs["timeout"] == 5
    body = json.loads(request.data)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["maxOutputTokens"] == ai_provider.MAX_OUTPUT_TOKENS
    assert "thinkingConfig" not in body["generationConfig"]  # model default unless configured
    assert result.text == "{}"
    assert "secret-key-123" not in repr(provider)


@pytest.mark.parametrize(("override", "used"), [(2.0, 2.0), (50.0, 5), (None, 5)])
def test_per_call_timeout_can_only_shorten_the_limit(
    provider: GeminiProvider, override: float | None, used: float
) -> None:
    with mock.patch("urllib.request.urlopen", return_value=FakeResponse(gemini_body("{}"))) as call:
        provider.generate(PROMPT, timeout_seconds=override)
    assert call.call_args.kwargs["timeout"] == used


def test_thinking_level_is_sent_when_configured() -> None:
    fast = GeminiProvider(api_key="k", model="m", timeout_seconds=5, thinking_level="low")
    with mock.patch("urllib.request.urlopen", return_value=FakeResponse(gemini_body("{}"))) as call:
        fast.generate(PROMPT)
    body = json.loads(call.call_args.args[0].data)
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}


def test_unknown_thinking_level_is_refused() -> None:
    with pytest.raises(ValueError):
        GeminiProvider(api_key="k", model="m", timeout_seconds=5, thinking_level="turbo")


def test_slowly_trickling_response_stops_at_the_deadline(provider: GeminiProvider) -> None:
    clock = FakeClock()
    provider._clock = clock

    class Trickle(FakeResponse):
        def read(self, limit: int) -> bytes:
            clock.now += 2  # every chunk arrives 2 s after the previous one
            return b" "

    with mock.patch("urllib.request.urlopen", return_value=Trickle(b"")):
        with pytest.raises(ProviderError) as caught:
            provider.generate(PROMPT)
    assert caught.value.code == "ai_timeout"


@pytest.mark.parametrize(
    ("failure", "code", "status"),
    [
        (http_error(429), "ai_rate_limited", 429),
        (http_error(401), "ai_auth_failed", 502),
        (http_error(403), "ai_auth_failed", 502),
        (http_error(400), "ai_request_rejected", 502),
        (http_error(404), "ai_model_not_found", 502),
        (http_error(500), "ai_provider_error", 502),
        (http_error(503), "ai_provider_error", 502),
        (http_error(409), "ai_unavailable", 502),
        (http_error(504), "ai_timeout", 504),
        (TimeoutError(), "ai_timeout", 504),
        (urllib.error.URLError(TimeoutError()), "ai_timeout", 504),
        (urllib.error.URLError("name resolution failed"), "ai_network_error", 502),
        (ConnectionResetError("reset"), "ai_network_error", 502),
    ],
    ids=[
        "429", "401", "403", "400", "404", "500", "503", "409", "504",
        "timeout", "url-timeout", "dns", "reset",
    ],
)
def test_transport_failures(provider: GeminiProvider, failure, code: str, status: int) -> None:
    with mock.patch("urllib.request.urlopen", side_effect=failure):
        with pytest.raises(ProviderError) as caught:
            provider.generate(PROMPT)
    assert (caught.value.code, caught.value.http_status) == (code, status)
    assert "sensitive body" not in caught.value.message
    assert "secret-key-123" not in caught.value.message


def test_error_message_names_status_and_google_enum_but_not_body(
    provider: GeminiProvider,
) -> None:
    failure = http_error(404, google_error(404, "NOT_FOUND"))
    with mock.patch("urllib.request.urlopen", side_effect=failure):
        with pytest.raises(ProviderError) as caught:
            provider.generate(PROMPT)
    message = caught.value.message
    assert "HTTP 404" in message and "NOT_FOUND" in message
    assert "gemini-2.5-flash" in message and "GEMINI_MODEL" in message
    assert "sensitive message" not in message


def test_unsafe_google_status_is_dropped(provider: GeminiProvider) -> None:
    failure = http_error(400, google_error(400, "contains the key secret-key-123"))
    with mock.patch("urllib.request.urlopen", side_effect=failure):
        with pytest.raises(ProviderError) as caught:
            provider.generate(PROMPT)
    assert caught.value.message.startswith("The AI provider rejected the request (HTTP 400)")
    assert "secret-key-123" not in caught.value.message


def test_network_error_names_only_the_exception_type(provider: GeminiProvider) -> None:
    failure = urllib.error.URLError(ssl.SSLCertVerificationError("cert detail /private/path"))
    with mock.patch("urllib.request.urlopen", side_effect=failure):
        with pytest.raises(ProviderError) as caught:
            provider.generate(PROMPT)
    assert "SSLCertVerificationError" in caught.value.message
    assert "/private/path" not in caught.value.message


def test_overloaded_model_is_retried_once(provider: GeminiProvider) -> None:
    waits: list[float] = []
    provider._sleep = waits.append
    responses = [http_error(503), FakeResponse(gemini_body('{"ok": true}'))]
    with mock.patch("urllib.request.urlopen", side_effect=responses) as call:
        result = provider.generate(PROMPT)
    assert result.text == '{"ok": true}'
    assert call.call_count == 2
    assert waits == [ai_provider.RETRY_DELAY_SECONDS]


def test_retry_gives_up_after_second_failure(provider: GeminiProvider) -> None:
    responses = [http_error(503), http_error(503, google_error(503, "UNAVAILABLE"))]
    with mock.patch("urllib.request.urlopen", side_effect=responses) as call:
        with pytest.raises(ProviderError) as caught:
            provider.generate(PROMPT)
    assert call.call_count == 2
    assert caught.value.code == "ai_provider_error"
    assert "HTTP 503, UNAVAILABLE" in caught.value.message


def test_slow_overload_failure_is_not_retried(provider: GeminiProvider) -> None:
    clock = FakeClock()
    provider._clock = clock

    def slow_failure(*_args: object, **_kwargs: object) -> None:
        clock.now += ai_provider.RETRY_ONLY_IF_FAILED_WITHIN_SECONDS + 1
        raise http_error(503)

    with mock.patch("urllib.request.urlopen", side_effect=slow_failure) as call:
        with pytest.raises(ProviderError) as caught:
            provider.generate(PROMPT)
    assert caught.value.code == "ai_provider_error"
    assert call.call_count == 1


@pytest.mark.parametrize("code", [400, 404, 429], ids=["400", "404", "429"])
def test_client_errors_are_not_retried(provider: GeminiProvider, code: int) -> None:
    with mock.patch("urllib.request.urlopen", side_effect=[http_error(code)]) as call:
        with pytest.raises(ProviderError):
            provider.generate(PROMPT)
    assert call.call_count == 1


def test_call_log_line_shows_status_without_secrets(
    provider: GeminiProvider, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="app.services.ai_provider")
    failure = http_error(404, google_error(404, "NOT_FOUND"))
    with mock.patch("urllib.request.urlopen", side_effect=failure):
        with pytest.raises(ProviderError):
            provider.generate(PROMPT)
    text = caplog.text
    assert "http_status=404" in text and "google_status=NOT_FOUND" in text
    assert "error_code=ai_model_not_found" in text
    assert "secret-key-123" not in text and "sensitive message" not in text


@pytest.mark.parametrize(
    "body",
    [
        b"<html>not json</html>",
        b'{"candidates": []}',
        b'{"promptFeedback": {"blockReason": "SAFETY"}}',
        gemini_body("{", finish="MAX_TOKENS"),
        gemini_body("   "),
        b"x" * (ai_provider.MAX_RESPONSE_BYTES + 10),
    ],
    # explicit ids: a 1 MB parameter would otherwise become the test id, which pytest
    # copies into an environment variable (Windows limits those to 32,767 characters)
    ids=["not-json", "no-candidates", "blocked", "max-tokens", "empty-text", "too-large"],
)
def test_unusable_responses(provider: GeminiProvider, body: bytes) -> None:
    with mock.patch("urllib.request.urlopen", return_value=FakeResponse(body)):
        with pytest.raises(ProviderError) as caught:
            provider.generate(PROMPT)
    assert caught.value.code == "ai_bad_response"


def test_blank_key_is_not_configured() -> None:
    with pytest.raises(ProviderError) as caught:
        GeminiProvider(api_key="   ", model="m", timeout_seconds=5)
    assert caught.value.code == "ai_not_configured"


# --------------------------------------------------------------------------- prompt + parsing


def test_prompt_sends_flattened_facts_and_rules() -> None:
    prompt = build_prompt(METRICS)
    payload = json.loads(prompt.user)
    assert payload["FACTS"]["production.actual_quantity"] == 95
    assert payload["FACTS"]["quality.defect_rate"] is None
    assert payload["LIMITATIONS"] == ["No shift time window was given."]
    assert not any(key.startswith("limitations") for key in payload["FACTS"])
    assert "Never invent" in prompt.system


def _report(evidence: list[str]) -> str:
    return json.dumps(
        {
            "executive_summary": "Summary.",
            "production_performance": [
                {"statement": "Output was 95.", "kind": "measured_fact", "evidence": evidence}
            ],
            "quality_observations": [],
            "downtime_maintenance_observations": [],
            "recommendations": [],
            "data_limitations": [],
        }
    )


def test_parse_accepts_known_evidence() -> None:
    report = parse_report(_report(["production.actual_quantity"]), METRICS)
    assert report.production_performance[0].evidence == ["production.actual_quantity"]


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        _report(["production.invented"]),
        _report([]),
        json.dumps({"executive_summary": "only this"}),
        json.dumps([1, 2, 3]),
    ],
)
def test_parse_rejects_invalid_output(text: str) -> None:
    with pytest.raises(ProviderError) as caught:
        parse_report(text, METRICS)
    assert caught.value.code == "ai_invalid_output"
    assert text not in caught.value.message