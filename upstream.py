"""Kaynak başına süreç içi HTTP sınırları ve son bağlantı durumu."""
import asyncio
import math
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

HOSTS = {
    "bedesten.adalet.gov.tr": "Bedesten", "kararlarbilgibankasi.anayasa.gov.tr": "AYM",
    "hudoc.echr.coe.int": "HUDOC", "tez.yok.gov.tr": "YÖK Tez",
    "www.resmigazete.gov.tr": "Resmî Gazete", "www.lexpera.com.tr": "LEXPERA",
}


class Gate:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.next_request = 0.0
        self.blocked_until = 0.0
        self.last = None
        self.status = "henüz denenmedi"


gates = {host: Gate() for host in HOSTS}


def retry_seconds(header):
    if header and header.isascii() and header.isdigit():
        return max(1, int(header))
    if header:
        try:
            return max(1, math.ceil(parsedate_to_datetime(header).timestamp() - time.time()))
        except (ValueError, TypeError, OverflowError):
            pass
    return 60


async def request(client, method, url, **kwargs):
    host = urlsplit(url).hostname
    gate = gates[host]
    async with gate.lock:
        wait = math.ceil(gate.blocked_until - time.monotonic())
        if wait > 0:
            raise httpx.RequestError(f"{HOSTS[host]}: {wait} saniye sonra deneyin.")
        await asyncio.sleep(max(0, gate.next_request - time.monotonic()))
        gate.next_request = time.monotonic() + (3 if host.startswith("bedesten.") else 1)
        gate.last = datetime.now(timezone.utc).isoformat()
        try:
            async with client.stream(method, url, **kwargs) as response:
                status = response.status_code
                if status in (403, 429) or status >= 500:
                    delay = retry_seconds(response.headers.get("Retry-After"))
                    gate.blocked_until = time.monotonic() + delay
                gate.status = f"HTTP {status}"
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(body) + len(chunk) > 24 * 1024 * 1024:
                        raise ValueError(f"{HOSTS[host]} yanıtı 24 MiB sınırını aştı.")
                    body.extend(chunk)
                # İçerik zaten açıldı; Content-Encoding ikinci kez uygulanmasın.
                return httpx.Response(status, content=bytes(body), request=response.request,
                                      headers={"Content-Type": response.headers.get("Content-Type", "")})
        except httpx.TransportError as exc:
            gate.status = type(exc).__name__
            gate.blocked_until = time.monotonic() + 30
            raise


def json_object(response, source):
    try:
        data = response.json()
    except ValueError as exc:
        raise ValueError(f"{source} okunabilir JSON döndürmedi.") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{source} yanıt yapısı değişti; bir JSON nesnesi bekleniyordu.")
    return data


async def kaynak_durumu() -> dict:
    """Son HTTP gözlemini ve kalan beklemeyi gösterir; kaynaklara yeni sorgu göndermez."""
    return {HOSTS[host]: {"son_http_durumu": gate.status, "son_deneme": gate.last,
                          "bekleme_saniye": max(0, math.ceil(gate.blocked_until - time.monotonic()))}
            for host, gate in gates.items()}
