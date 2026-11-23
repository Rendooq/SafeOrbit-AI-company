"""Validate customer-controlled outbound targets before sending secrets or data."""
import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


async def validate_public_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.fragment or parsed.port not in (None, 443):
            raise ValueError("Use public HTTPS without credentials")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None and not literal.is_global:
            raise ValueError("Private IP literals are forbidden")
        addresses = await asyncio.to_thread(socket.getaddrinfo, host, 443, 0, socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError("Private networks are forbidden")
    except (OSError, ValueError) as error:
        raise ValueError("URL must resolve to a public HTTPS destination") from error
    return url
