"""Tests for LLM's HTTP error detection: 429 (rate limited) and 403 (forbidden, e.g. a model
that requires a paid Ollama subscription the account doesn't have) both need to stop a batch
run rather than be treated like an ordinary per-item failure.

No PyQt6 dependency - lib.llm has none.
"""

import io
import json
from email.message import Message
from urllib.error import HTTPError

import pytest

from lib.llm import (
    LLM,
    LLMBatchStoppingException,
    LLMForbiddenException,
    LLMRateLimitException,
    LLMResponseException,
)


def _make_http_error(code=429, msg="Too Many Requests", body=b"", headers=None):
    hdrs = Message()
    for key, value in (headers or {}).items():
        hdrs[key] = value
    return HTTPError(
        url="http://localhost:11434/api/generate",
        code=code,
        msg=msg,
        hdrs=hdrs,
        fp=io.BytesIO(body),
    )


class TestExceptionHierarchy:
    def test_rate_limit_and_forbidden_are_batch_stopping(self):
        assert issubclass(LLMRateLimitException, LLMBatchStoppingException)
        assert issubclass(LLMForbiddenException, LLMBatchStoppingException)
        assert issubclass(LLMBatchStoppingException, LLMResponseException)


class TestBuildHttpErrorMessage:
    def test_includes_server_error_message(self):
        err = _make_http_error(body=json.dumps({"error": "rate limit exceeded"}).encode())
        msg = LLM._build_http_error_message("Rate limited (HTTP 429).", err)
        assert "429" in msg
        assert "rate limit exceeded" in msg

    def test_includes_retry_after_only_when_requested(self):
        err = _make_http_error(body=b"{}", headers={"Retry-After": "30"})
        with_retry = LLM._build_http_error_message("Rate limited.", err, include_retry_after=True)
        assert "30" in with_retry

    def test_omits_retry_after_when_not_requested(self):
        err = _make_http_error(code=403, body=b"{}", headers={"Retry-After": "30"})
        without_retry = LLM._build_http_error_message("Forbidden.", err, include_retry_after=False)
        assert "30" not in without_retry

    def test_tolerates_non_json_body(self):
        err = _make_http_error(body=b"not json")
        msg = LLM._build_http_error_message("Rate limited (HTTP 429).", err)
        assert "429" in msg

    def test_tolerates_empty_body_and_no_headers(self):
        err = _make_http_error(body=b"")
        msg = LLM._build_http_error_message("Rate limited (HTTP 429).", err)
        assert "429" in msg


def _raising_urlopen(err):
    """Build a urlopen(req, timeout=...) replacement that always raises err."""
    def _urlopen(req, timeout=None):
        raise err
    return _urlopen


class TestGenerateResponseRateLimit:
    def test_429_raises_llm_rate_limit_exception(self, monkeypatch):
        llm = LLM(model_name="test-model", state_key="test-rate-limit-1")
        err = _make_http_error(code=429, body=json.dumps({"error": "slow down"}).encode())
        monkeypatch.setattr("lib.llm.request.urlopen", _raising_urlopen(err))

        with pytest.raises(LLMRateLimitException) as exc_info:
            llm.generate_response("hello")
        assert "slow down" in str(exc_info.value)

    def test_other_http_errors_raise_generic_exception_not_a_batch_stopping_one(self, monkeypatch):
        llm = LLM(model_name="test-model", state_key="test-rate-limit-2")
        err = _make_http_error(code=500, msg="Internal Server Error", body=b'{"error": "internal error"}')
        monkeypatch.setattr("lib.llm.request.urlopen", _raising_urlopen(err))

        with pytest.raises(LLMResponseException) as exc_info:
            llm.generate_response("hello")
        assert not isinstance(exc_info.value, LLMBatchStoppingException)

    def test_rate_limit_type_preserved_through_async_and_json_helpers(self, monkeypatch):
        # Regression: generate_response_async used to re-wrap every exception into a plain
        # LLMResponseException, which would lose the LLMRateLimitException type that callers
        # (TranslationService, the bulk translation worker) need to detect and act on.
        llm = LLM(model_name="test-model", state_key="test-rate-limit-3")
        err = _make_http_error(code=429, body=json.dumps({"error": "slow down"}).encode())
        monkeypatch.setattr("lib.llm.request.urlopen", _raising_urlopen(err))

        with pytest.raises(LLMRateLimitException):
            llm.generate_json_get_value("hello", json_key="translation")

    def test_failure_count_increments_on_rate_limit(self, monkeypatch):
        llm = LLM(model_name="test-model", state_key="test-rate-limit-4")
        err = _make_http_error(code=429, body=b"{}")
        monkeypatch.setattr("lib.llm.request.urlopen", _raising_urlopen(err))

        assert llm.get_failure_count() == 0
        with pytest.raises(LLMRateLimitException):
            llm.generate_response("hello")
        assert llm.get_failure_count() == 1


class TestGenerateResponseForbidden:
    def test_403_raises_llm_forbidden_exception(self, monkeypatch):
        llm = LLM(model_name="test-model", state_key="test-forbidden-1")
        err = _make_http_error(
            code=403,
            msg="Forbidden",
            body=json.dumps(
                {"error": "this model requires a subscription, upgrade for access: https://ollama.com/upgrade"}
            ).encode(),
        )
        monkeypatch.setattr("lib.llm.request.urlopen", _raising_urlopen(err))

        with pytest.raises(LLMForbiddenException) as exc_info:
            llm.generate_response("hello")
        assert "requires a subscription" in str(exc_info.value)
        assert "403" in str(exc_info.value)

    def test_403_message_has_no_retry_after_even_if_header_present(self, monkeypatch):
        # A 403 is permanent (wrong plan/auth), not transient - retrying after a delay wouldn't
        # help, so unlike 429 the message shouldn't suggest one even if a header is present.
        llm = LLM(model_name="test-model", state_key="test-forbidden-2")
        err = _make_http_error(code=403, body=b"{}", headers={"Retry-After": "30"})
        monkeypatch.setattr("lib.llm.request.urlopen", _raising_urlopen(err))

        with pytest.raises(LLMForbiddenException) as exc_info:
            llm.generate_response("hello")
        assert "30" not in str(exc_info.value)

    def test_forbidden_type_preserved_through_async_and_json_helpers(self, monkeypatch):
        llm = LLM(model_name="test-model", state_key="test-forbidden-3")
        err = _make_http_error(code=403, body=json.dumps({"error": "requires a subscription"}).encode())
        monkeypatch.setattr("lib.llm.request.urlopen", _raising_urlopen(err))

        with pytest.raises(LLMForbiddenException):
            llm.generate_json_dict("hello")

    def test_failure_count_increments_on_forbidden(self, monkeypatch):
        llm = LLM(model_name="test-model", state_key="test-forbidden-4")
        err = _make_http_error(code=403, body=b"{}")
        monkeypatch.setattr("lib.llm.request.urlopen", _raising_urlopen(err))

        assert llm.get_failure_count() == 0
        with pytest.raises(LLMForbiddenException):
            llm.generate_response("hello")
        assert llm.get_failure_count() == 1
