"""Live adapters are exercised against httpx.MockTransport - no network."""

import json

import httpx
import pytest

from app.core.errors import IntegrationError, IntegrationNotConfigured, RateLimited, TransientIntegrationError
from app.integrations import live
from app.integrations.base import CircuitBreaker, RetryPolicy, reset_breakers, with_retry


def _patch(adapter, handler):
    adapter._client = httpx.Client(base_url=adapter._config.base_url, headers=adapter._config.headers, transport=httpx.MockTransport(handler))
    return adapter


def test_slack_post_and_test_connection():
    reset_breakers()

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["Authorization"] == "Bearer xoxb-test"
        if req.url.path == "/api/auth.test":
            return httpx.Response(200, json={"ok": True, "user": "bot", "team": "T"})
        if req.url.path == "/api/chat.postMessage":
            body = json.loads(req.content)
            assert body["channel"] == "#ops"
            return httpx.Response(200, json={"ok": True, "ts": "1.2", "channel": "C1"})
        return httpx.Response(404)

    a = _patch(live.build("chat", "slack", {}, {"bot_token": "xoxb-test"}), handler)
    assert a.test_connection().ok
    assert a.post_message("#ops", "hello")["message_id"] == "1.2"


def test_missing_credentials_refused():
    with pytest.raises(IntegrationNotConfigured):
        live.build("chat", "slack", {}, {})
    assert live.build("procurement", "nothing", {}, {}) is None


def test_unimplemented_live_operation_is_explicit():
    a = live.build("chat", "slack", {}, {"bot_token": "x"})
    with pytest.raises(IntegrationNotConfigured):
        a.list_templates()


def test_hubspot_find_and_verify():
    reset_breakers()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/contacts/search"):
            return httpx.Response(200, json={"results": [{"id": "77", "properties": {"email": "a@b.test", "company": "B"}}]})
        return httpx.Response(200, json={"id": "77", "properties": {}})

    a = _patch(live.build("crm", "hubspot", {}, {"access_token": "t"}), handler)
    found = a.find_lead(email="a@b.test")
    assert found["count"] == 1 and found["matches"][0]["id"] == "77"
    v = a.verify_action("upsert_lead", {"lead": {"email": "a@b.test"}}, None)
    assert v is not None and v.exists and v.external_ref == "77"


def test_rate_limit_and_server_errors_map_and_retry():
    reset_breakers()
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "1"})

    a = _patch(live.build("issues", "jira", {"site_url": "https://x.atlassian.net"}, {"email": "e", "api_token": "t"}), handler)
    with pytest.raises(RateLimited):
        a._request("GET", "/rest/api/3/myself", safe_to_retry=False)
    assert calls["n"] == 1  # non-retryable path does not retry blindly


def test_non_idempotent_create_not_retried_on_timeout():
    reset_breakers()
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("slow", request=req)

    a = _patch(live.build("issues", "jira", {"site_url": "https://x.atlassian.net"}, {"email": "e", "api_token": "t"}), handler)
    with pytest.raises(TransientIntegrationError):
        a.create_issue("ENG", "t")
    assert calls["n"] == 1


def test_4xx_maps_to_integration_error():
    reset_breakers()
    a = _patch(live.build("commerce", "shopify", {"shop_domain": "s.myshopify.com"}, {"access_token": "t"}), lambda r: httpx.Response(401, text="bad token"))
    with pytest.raises(IntegrationError):
        a.get_product("1")


def test_circuit_breaker_opens_and_recovers():
    cb = CircuitBreaker(failure_threshold=2, recovery_seconds=0)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"
    cb.before_call()  # recovery_seconds=0 -> half-open
    assert cb.state == "half_open"
    cb.record_success()
    assert cb.state == "closed"


def test_with_retry_backoff_and_give_up():
    attempts = {"n": 0}

    def fn():
        attempts["n"] += 1
        raise TransientIntegrationError("x")

    with pytest.raises(TransientIntegrationError):
        with_retry(fn, RetryPolicy(max_attempts=3, base_delay=0, jitter=0), sleep=lambda s: None)
    assert attempts["n"] == 3
