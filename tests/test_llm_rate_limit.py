"""Tests for LLM's HTTP 429 (rate limit) detection and message building.

No PyQt6 dependency - lib.llm has none.
"""

import io
import json
from email.message import Message
from urllib.error import HTTPError

import pytest

from lib.llm import LLM, LLMRateLimitException, LLMResponseException


def _make_http_error(code=429, body=b"", headers=None):
    hdrs = Message()
    for key, value in (headers or {}).items():
        hdrs[key] = value
    return HTTPError(
        url="http://localhost:11434/api/generate",
        code=code,
        msg="Too Many Requests",
        hdrs=hdrs,
        fp=io.BytesIO(body),
    )


class TestBuildRateLimitMessage:
    def test_includes_server_error_message(self):
        err = _make_http_error(body=json.dumps({"error": "rate limit exceeded"}).encode())
        msg = LLM._build_rate_limit_message(err)
        assert "429" in msg
        assert "rate limit exceeded" in msg

    def test_includes_retry_after_when_present(self):
        err = _make_http_error(body=b"{}", headers={"Retry-After": "30"})
        msg = LLM._build_rate_limit_message(err)
        assert "30" in msg

    def test_tolerates_non_json_body(self):
        err = _make_http_error(body=b"not json")
        msg = LLM._build_rate_limit_message(err)
        assert "429" in msg

    def test_tolerates_empty_body_and_no_headers(self):
        err = _make_http_error(body=b"")
        msg = LLM._build_rate_limit_message(err)
        assert "429" in msg


def _raising_urlopen(err):
    """Build a urlopen(req, timeout=...) replacement that always raises err."""
    def _urlopen(req, timeout=None):
        raise err
    return _urlopen


class TestGenerateResponseRateLimit:
    def test_429_raises_llm_rate_limit_exception(self, monkeypatch):
        llm = LLM(model_name="test-model", state_key="test-rate-limit-1")
        err = _make_http_error(body=json.dumps({"error": "slow down"}).encode())
        monkeypatch.setattr("lib.llm.request.urlopen", _raising_urlopen(err))

        with pytest.raises(LLMRateLimitException) as exc_info:
            llm.generate_response("hello")
        assert "slow down" in str(exc_info.value)

    def test_other_http_errors_raise_generic_exception_not_rate_limit(self, monkeypatch):
        llm = LLM(model_name="test-model", state_key="test-rate-limit-2")
        err = _make_http_error(code=500, body=b'{"error": "internal error"}')
        monkeypatch.setattr("lib.llm.request.urlopen", _raising_urlopen(err))

        with pytest.raises(LLMResponseException) as exc_info:
            llm.generate_response("hello")
        assert not isinstance(exc_info.value, LLMRateLimitException)

    def test_rate_limit_type_preserved_through_async_and_json_helpers(self, monkeypatch):
        # Regression: generate_response_async used to re-wrap every exception into a plain
        # LLMResponseException, which would lose the LLMRateLimitException type that callers
        # (TranslationService, the bulk translation worker) need to detect and act on.
        llm = LLM(model_name="test-model", state_key="test-rate-limit-3")
        err = _make_http_error(body=json.dumps({"error": "slow down"}).encode())
        monkeypatch.setattr("lib.llm.request.urlopen", _raising_urlopen(err))

        with pytest.raises(LLMRateLimitException):
            llm.generate_json_get_value("hello", json_key="translation")

    def test_failure_count_increments_on_rate_limit(self, monkeypatch):
        llm = LLM(model_name="test-model", state_key="test-rate-limit-4")
        err = _make_http_error(body=b"{}")
        monkeypatch.setattr("lib.llm.request.urlopen", _raising_urlopen(err))

        assert llm.get_failure_count() == 0
        with pytest.raises(LLMRateLimitException):
            llm.generate_response("hello")
        assert llm.get_failure_count() == 1
