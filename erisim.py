"""Bağımsız HTTP sunucusu ve yönetilen ağ geçidi yapılandırması."""
import ipaddress
import os

from fastmcp.server.auth.providers.jwt import JWTVerifier


def token_verifier():
    settings = [os.getenv(name) for name in ("MCP_JWT_PUBLIC_KEY", "MCP_JWT_ISSUER", "MCP_JWT_AUDIENCE")]
    if not any(settings):
        return None
    if not all(settings):
        raise ValueError("JWT açık anahtarı, issuer ve audience birlikte ayarlanmalı.")
    key, issuer, audience = settings
    return JWTVerifier(public_key=key.replace("\\n", "\n"), issuer=issuer,
                       audience=audience, algorithm="RS256")


def http_host(authenticated):
    host = os.getenv("MCP_HOST", "127.0.0.1")
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == "localhost"
    if not local and not authenticated and os.getenv("MCP_TRUSTED_GATEWAY") != "1":
        raise ValueError("Genel HTTP için JWT ayarlayın veya yalnızca korumalı ağda MCP_TRUSTED_GATEWAY=1 kullanın.")
    return host
