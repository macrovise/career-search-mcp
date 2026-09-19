import ipaddress

import pytest

from jobsearch_mcp import security
from jobsearch_mcp.auth import auth_provider
from jobsearch_mcp.http import fetch


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://127.0.0.1",
        "https://100.64.0.1",
        "https://[::1]",
        "https://169.254.169.254",
        "https://[::ffff:10.0.0.1]",
    ],
)
def test_ssrf_blocked(url):
    with pytest.raises(ValueError):
        security._validate_url(url)


def test_all_dns_results_checked(monkeypatch):
    monkeypatch.setattr(
        security,
        "_resolve_host",
        lambda _: [ipaddress.ip_address("8.8.8.8"), ipaddress.ip_address("10.0.0.1")],
    )
    with pytest.raises(ValueError):
        security._validate_url("https://example.com")


async def test_redirect_to_private_blocked(respx_mock, monkeypatch):
    monkeypatch.setattr(security, "_resolve_host", lambda _: [ipaddress.ip_address("8.8.8.8")])
    respx_mock.get("https://example.com").respond(
        302, headers={"Location": "https://127.0.0.1/secret"}
    )
    with pytest.raises(ValueError):
        await fetch("https://example.com")


async def test_api_credentials_not_redirected(respx_mock, monkeypatch):
    monkeypatch.setattr(security, "_resolve_host", lambda _: [ipaddress.ip_address("8.8.8.8")])
    respx_mock.get("https://example.com", params={"app_key": "test-secret"}).respond(
        302, headers={"Location": "https://elsewhere.example"}
    )
    with pytest.raises(ValueError):
        await fetch("https://example.com", {"app_key": "test-secret"})


def test_fail_closed_without_auth_configuration(monkeypatch):
    monkeypatch.delenv("CAREER_AUTH_MODE", raising=False)
    monkeypatch.delenv("CAREER_PUBLIC_URL", raising=False)
    with pytest.raises(ValueError):
        auth_provider()


def test_local_auth_cannot_bind_publicly(monkeypatch):
    monkeypatch.setenv("CAREER_AUTH_MODE", "local")
    monkeypatch.setenv("MCP_HOST", "0.0.0.0")
    with pytest.raises(ValueError):
        auth_provider()


async def test_every_same_origin_redirect_revalidates_dns(respx_mock, monkeypatch):
    calls = []

    def resolve(host):
        calls.append(host)
        return [ipaddress.ip_address("8.8.8.8" if len(calls) == 1 else "10.0.0.1")]

    monkeypatch.setattr(security, "_resolve_host", resolve)
    respx_mock.get("https://example.com/start").respond(302, headers={"Location": "/next"})
    with pytest.raises(ValueError):
        await fetch("https://example.com/start")
    assert len(calls) == 2


async def test_response_size_limit(respx_mock, monkeypatch):
    import jobsearch_mcp.http as safe_http

    monkeypatch.setattr(security, "_resolve_host", lambda _: [ipaddress.ip_address("8.8.8.8")])
    monkeypatch.setattr(safe_http, "MAX_BYTES", 10)
    respx_mock.get("https://example.com/large").respond(200, content=b"a" * 11)
    with pytest.raises(ValueError, match="size limit"):
        await fetch("https://example.com/large")
