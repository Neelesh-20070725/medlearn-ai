"""
Tests for the sliding-window rate limiter (main.py section 5) and the
get_client_ip helper it depends on for keying by IP.
"""
import time

import pytest


@pytest.fixture(autouse=True)
def clear_rate_limit_state(app):
    """Every test starts with a clean in-memory bucket - otherwise tests
    would interfere with each other depending on run order."""
    app._in_memory_rate_buckets.clear()
    yield
    app._in_memory_rate_buckets.clear()


def test_under_limit_does_not_raise(app):
    for _ in range(5):
        app.check_rate_limit("test:key1", max_requests=5, window_seconds=60)
    # no exception = pass


def test_exceeding_limit_raises(app):
    for _ in range(5):
        app.check_rate_limit("test:key1", max_requests=5, window_seconds=60)
    with pytest.raises(app.RateLimitExceeded) as exc_info:
        app.check_rate_limit("test:key1", max_requests=5, window_seconds=60)
    assert exc_info.value.retry_after_seconds == 60


def test_different_keys_tracked_independently(app):
    for _ in range(5):
        app.check_rate_limit("test:key1", max_requests=5, window_seconds=60)
    # key2 should be unaffected by key1 being exhausted
    app.check_rate_limit("test:key2", max_requests=5, window_seconds=60)


def test_sliding_window_expires_old_entries(app):
    """The core correctness property of a SLIDING window, as opposed to a
    permanent lockout: once enough time passes, old requests age out and
    new ones succeed again."""
    app.check_rate_limit("test:key3", max_requests=1, window_seconds=0.2)
    with pytest.raises(app.RateLimitExceeded):
        app.check_rate_limit("test:key3", max_requests=1, window_seconds=0.2)

    time.sleep(0.3)
    app.check_rate_limit("test:key3", max_requests=1, window_seconds=0.2)  # should not raise


def test_rate_limit_response_returns_429_with_retry_after(app):
    resp = app.rate_limit_response(app.RateLimitExceeded(retry_after_seconds=42))
    assert resp.status_code == 429
    assert resp.headers.get("retry-after") == "42"


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, headers=None, client_host="10.0.0.5"):
        self.headers = headers or {}
        self.client = _FakeClient(client_host) if client_host else None


def test_get_client_ip_uses_x_forwarded_for(app):
    req = _FakeRequest(headers={"x-forwarded-for": "203.0.113.7"})
    assert app.get_client_ip(req) == "203.0.113.7"


def test_get_client_ip_takes_first_ip_in_proxy_chain(app):
    req = _FakeRequest(headers={"x-forwarded-for": "203.0.113.7, 10.0.0.1, 10.0.0.2"})
    assert app.get_client_ip(req) == "203.0.113.7"


def test_get_client_ip_falls_back_to_direct_connection(app):
    req = _FakeRequest(headers={}, client_host="192.168.1.1")
    assert app.get_client_ip(req) == "192.168.1.1"


def test_get_client_ip_handles_missing_client_gracefully(app):
    req = _FakeRequest(headers={}, client_host=None)
    assert app.get_client_ip(req) == "unknown"
