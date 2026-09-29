import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp.server.auth import RemoteAuthProvider

from jobsearch_mcp.auth import OwnerJWTVerifier
from jobsearch_mcp.server import create_server
from jobsearch_mcp.store import Store


@pytest.fixture
def keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private, public


def claims():
    return {
        "sub": "trevor-test",
        "iss": "https://identity.example/",
        "aud": "https://career.example/mcp",
        "scope": "career:access",
        "exp": int(time.time()) + 300,
    }


def verifier(keys):
    return OwnerJWTVerifier(
        owner_subject="trevor-test",
        public_key=keys[1],
        algorithm="RS256",
        issuer="https://identity.example/",
        audience="https://career.example/mcp",
        required_scopes=["career:access"],
    )


async def test_valid_owner(keys):
    assert await verifier(keys).verify_token(jwt.encode(claims(), keys[0], algorithm="RS256"))


@pytest.mark.parametrize(
    "updates",
    [
        {"sub": "another-user"},
        {"aud": "https://wrong.example"},
        {"iss": "https://wrong.example/"},
        {"scope": "other"},
        {"exp": 1},
        {"exp": None},
        {"nbf": time.time() + 600},
    ],
)
async def test_invalid_token_claims(keys, updates):
    data = claims() | updates
    token = jwt.encode(data, keys[0], algorithm="RS256")
    assert await verifier(keys).verify_token(token) is None


async def test_wrong_signature(keys):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert await verifier(keys).verify_token(jwt.encode(claims(), other, algorithm="RS256")) is None


async def test_http_auth_and_resource_metadata(keys, tmp_path, monkeypatch):
    import jobsearch_mcp.server as server

    provider = RemoteAuthProvider(
        token_verifier=verifier(keys),
        authorization_servers=["https://identity.example/"],
        base_url="https://career.example",
        resource_base_url="https://career.example",
        scopes_supported=["career:access"],
    )
    monkeypatch.setattr(server, "auth_provider", lambda: provider)
    app = create_server(Store(str(tmp_path / "db"))).http_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="https://career.example"
        ) as client,
    ):
        denied = await client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        assert denied.status_code == 401
        assert "resource_metadata" in denied.headers["www-authenticate"]
        response = await client.get("/.well-known/oauth-protected-resource/mcp")
        assert response.status_code == 200
        assert response.json()["resource"] == "https://career.example/mcp"
        token = jwt.encode(claims(), keys[0], algorithm="RS256")
        response = await client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        assert response.status_code == 200
        assert "Career Search MCP" in response.text
