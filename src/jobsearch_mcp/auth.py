"""Fail-closed OAuth resource server: signed tokens, audience, scope and owner."""

import os
import time
from urllib.parse import urlsplit

from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier


class OwnerJWTVerifier(JWTVerifier):
    def __init__(self, *, owner_subject: str, **kwargs):
        super().__init__(**kwargs)
        self.owner_subject = owner_subject

    async def verify_token(self, token):
        access = await super().verify_token(token)
        # A token from the same tenant is insufficient: this deployment is private.
        if (
            not access
            or access.claims.get("sub") != self.owner_subject
            or not access.claims.get("exp")
            or not isinstance(access.claims.get("nbf", 0), (int, float))
            or access.claims.get("nbf", 0) > time.time()
        ):
            return None
        return access


def https_setting(name: str) -> str:
    value = os.environ.get(name, "")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
    ):
        raise ValueError(
            f"{name} must be a configured HTTPS URL without credentials/query/fragment"
        )
    return value.rstrip("/")


def auth_provider():
    mode = os.getenv("CAREER_AUTH_MODE", "oauth")
    if mode == "local":
        if os.getenv("MCP_HOST", "127.0.0.1") not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("Unauthenticated local mode must bind to loopback")
        return None
    if mode != "oauth":
        raise ValueError("CAREER_AUTH_MODE must be oauth or local")
    base = https_setting("CAREER_PUBLIC_URL")
    issuer = https_setting("OAUTH_ISSUER")
    jwks = https_setting("OAUTH_JWKS_URL")
    owner = os.getenv("OAUTH_OWNER_SUBJECT", "")
    if not owner:
        raise ValueError("OAUTH_OWNER_SUBJECT is required")
    # Preserve issuer trailing slash: it is significant in the signed token.
    verifier = OwnerJWTVerifier(
        owner_subject=owner,
        jwks_uri=jwks,
        issuer=os.environ["OAUTH_ISSUER"],
        audience=base + "/mcp",
        algorithm="RS256",
        required_scopes=["career:access"],
        ssrf_safe=True,
    )
    return RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[issuer],
        base_url=base,
        resource_base_url=base,
        scopes_supported=["career:access"],
        resource_name="Career Search MCP",
    )
