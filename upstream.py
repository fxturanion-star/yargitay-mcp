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
        self.transport_failures = 0


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


TRANSPORT_FAILURES_BEFORE_COOLDOWN = 3
SERVER_ERROR_COOLDOWN = 10


def _check_blocked(host, gate):
    wait = math.ceil(gate.blocked_until - time.monotonic())
    if wait > 0:
        raise httpx.RequestError(f"{HOSTS[host]}: {wait} saniye sonra deneyin.")


async def request(client, method, url, **kwargs):
    host = urlsplit(url).hostname
    gate = gates[host]
    # Kilit yalnız başlangıç zamanını ayırır; istekler aralıklı başlar ama
    # yavaş bir yanıt sıradaki kullanıcıların isteğini bekletmez.
    async with gate.lock:
        _check_blocked(host, gate)
        start_at = max(time.monotonic(), gate.next_request)
        gate.next_request = start_at + (3 if host.startswith("bedesten.") else 1)
    await asyncio.sleep(max(0, start_at - time.monotonic()))
    _check_blocked(host, gate)
    gate.last = datetime.now(timezone.utc).isoformat()
    try:
        async with client.stream(method, url, **kwargs) as response:
            status = response.status_code
            # Yalnız kaynağın açıkça yük bildirdiği yanıtlar herkes için beklemeye yol açar.
            # Tek bir 403 veya 500 diğer kullanıcıların sorgusunu kapatmaz.
            if status in (429, 503):
                gate.blocked_until = time.monotonic() + retry_seconds(response.headers.get("Retry-After"))
            elif status >= 500:
                gate.blocked_until = max(gate.blocked_until, time.monotonic() + SERVER_ERROR_COOLDOWN)
            gate.status = f"HTTP {status}"
            gate.transport_failures = 0
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
        # Tek bir zaman aşımı kaynağı kapatmaz; art arda hatalarda kısa bekleme başlar.
        gate.transport_failures += 1
        if gate.transport_failures >= TRANSPORT_FAILURES_BEFORE_COOLDOWN:
            gate.blocked_until = time.monotonic() + 30
            gate.transport_failures = 0
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
