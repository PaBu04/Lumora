"""WLED HTTP JSON API and mDNS discovery."""

import asyncio
import math
import socket
import weakref

import httpx
from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

WLED_SERVICE = "_wled._tcp.local."

_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = weakref.WeakKeyDictionary()


def _client() -> httpx.AsyncClient:
    """One shared HTTP client per event loop.

    Creating an httpx client loads the system's TLS certificates, which blocks the event loop
    for ~300 ms on Windows - enough to freeze the live output. WLED only speaks plain HTTP,
    so the shared client skips TLS setup entirely."""
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None or client.is_closed:
        client = _new_client()
        _clients[loop] = client
    return client


def _new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(verify=False, limits=httpx.Limits(max_keepalive_connections=16))


async def warm_client() -> None:
    """Create the shared client in a worker thread so not even its first setup stalls the loop."""
    loop = asyncio.get_running_loop()
    if loop not in _clients:
        client = await asyncio.to_thread(_new_client)
        _clients.setdefault(loop, client)


async def fetch_info(host: str, timeout: float = 2.0) -> dict:
    """Summary of a WLED device from /json/info."""
    r = await _client().get(f"http://{host}/json/info", timeout=timeout)
    r.raise_for_status()
    info = r.json()
    leds = info.get("leds", {})
    lc = leds.get("lc", 1)
    wifi = info.get("wifi", {}) or {}
    return {
        "host": host,
        "name": info.get("name", host),
        "version": info.get("ver"),
        "mac": info.get("mac"),
        "led_count": leds.get("count", 0),
        "rgbw": bool(leds.get("rgbw", False) or (lc & 0x02)),
        "fps": leds.get("fps"),
        "max_power_ma": leds.get("maxpwr"),
        "arch": info.get("arch"),
        "live": info.get("live", False),
        "rssi": wifi.get("rssi"),
        "signal": wifi.get("signal"),
    }


# WLED bus types (const.h) of single-wire LEDs -> bits per LED; the rest is clocked/analog/network
_BITS = {
    18: 8,
    19: 8,
    20: 16,
    21: 24,
    22: 24,
    23: 24,
    24: 24,
    25: 24,
    26: 48,
    27: 24,
    28: 48,
    29: 64,
    30: 32,
    31: 32,
    32: 40,
    33: 24,
    34: 80,
}
_US_PER_BIT = {24: 2.5}  # WS2811 400 kHz; all others 800 kHz
WLED_OVERHEAD_MS = 5.0  # WLED loop, DDP handling, latch (measured: 873 WS2812B on one pin -> 32 FPS)
WLED_MAX_FPS = 50.0  # realtime frames WLED shows at most, even with few LEDs (measured ~51)
SAFETY = 0.92  # send a bit slower than the estimate so WLED never has to drop frames


def bus_ms(bus_type: int, length: int) -> float:
    """Time one LED data line needs to push a frame out."""
    bits = _BITS.get(bus_type)
    if bits is None:
        return 0.0
    return length * bits * _US_PER_BIT.get(bus_type, 1.25) / 1000.0 + 0.3  # + reset/latch


def estimate_fps(buses: list[dict]) -> float:
    """Frames per second WLED can display; parallel data pins output at the same time."""
    slowest = max((b["ms"] for b in buses), default=0.0)
    return round(min(WLED_MAX_FPS, 1000.0 / (slowest + WLED_OVERHEAD_MS)), 1)


async def fetch_config(host: str, timeout: float = 3.0) -> dict:
    """LED outputs and settings from /json/cfg that limit realtime output."""
    r = await _client().get(f"http://{host}/json/cfg", timeout=timeout)
    r.raise_for_status()
    cfg = r.json()
    buses = []
    for b in cfg.get("hw", {}).get("led", {}).get("ins") or []:
        t, n = int(b.get("type", 0)), int(b.get("len", 0))
        buses.append({"type": t, "len": n, "pins": b.get("pin", []), "ms": round(bus_ms(t, n), 2)})
    live = cfg.get("if", {}).get("live", {}) or {}
    return {
        "buses": buses,
        "max_fps": estimate_fps(buses),
        "wifi_sleep": bool((cfg.get("wifi") or {}).get("sleep", False)),
        "realtime": bool(live.get("en", True)),
        "timeout_s": (live.get("timeout") or 25) / 10.0,
    }


def recommended_fps(max_fps: float | None, cap: float) -> float:
    """Send rate for a controller: a little below what it can show, never above the render rate."""
    if not max_fps or max_fps >= WLED_MAX_FPS:  # LEDs are not the bottleneck
        return cap
    return float(max(5, math.floor(min(cap, max_fps * SAFETY))))


def limit_hint(cfg: dict | None) -> str | None:
    """Why a controller cannot go faster, in words, or None if it is not the bottleneck."""
    if not cfg or not cfg.get("buses") or cfg["max_fps"] >= WLED_MAX_FPS:
        return None
    slow = max(cfg["buses"], key=lambda b: b["ms"])
    pins = sum(1 for b in cfg["buses"] if b["ms"] > 0)
    text = f"max. ca. {cfg['max_fps']:.0f} FPS: {slow['len']} LEDs an einem Datenpin brauchen {slow['ms']:.0f} ms pro Bild"
    if pins <= 1:
        text += ". Für mehr FPS den Strip auf zwei oder mehr Datenpins aufteilen (in WLED je Pin ein Ausgang)"
    return text


async def controller_status(host: str, pixels: int, sent_fps: float, live: bool, cfg: dict | None = None) -> dict:
    """Reachability and health of one controller with human readable warnings."""
    try:
        info = await fetch_info(host, timeout=1.5)
    except Exception as exc:
        return {"ok": False, "error": f"nicht erreichbar ({type(exc).__name__})", "warnings": [], "hints": []}
    warnings, hints = [], []
    if info["led_count"] and pixels > info["led_count"]:
        warnings.append(f"WLED hat nur {info['led_count']} LEDs konfiguriert, zugeordnet sind {pixels}")
    if info.get("rssi") is not None and info["rssi"] < -75:
        warnings.append(f"schwaches WLAN ({info['rssi']} dBm): Pakete können verloren gehen")
    if cfg:
        if cfg.get("wifi_sleep"):
            warnings.append("WLAN-Energiesparen ist an: in WLED unter WiFi Setup „Disable WiFi sleep“ aktivieren")
        if not cfg.get("realtime", True):
            warnings.append("Empfang von Echtzeitdaten ist aus: in WLED unter Sync „Receive UDP realtime“ aktivieren")
        hint = limit_hint(cfg)
        if hint:
            hints.append(hint)
    if live and sent_fps >= 5 and info.get("fps") is not None and info["fps"] < 0.75 * sent_fps:
        warnings.append(
            f"WLED zeigt {info['fps']} von {sent_fps:.0f} gesendeten FPS: Pakete gehen verloren "
            "(WLAN) oder der Controller ist überlastet – „Geschwindigkeit messen“ hilft beim Einstellen"
        )
    return {"ok": True, "info": info, "config": cfg, "sent_fps": round(sent_fps, 1), "warnings": warnings, "hints": hints}


async def set_state(host: str, state: dict, timeout: float = 2.0) -> dict:
    r = await _client().post(f"http://{host}/json/state", json=state, timeout=timeout)
    r.raise_for_status()
    return r.json()


async def discover(seconds: float = 3.0) -> list[dict]:
    """Browse mDNS for WLED devices and return their info (devices that do not answer are listed with an error)."""
    found: dict[str, tuple[str, int]] = {}
    azc = AsyncZeroconf()
    pending: list[asyncio.Task] = []

    async def resolve(name: str) -> None:
        info = AsyncServiceInfo(WLED_SERVICE, name)
        if await info.async_request(azc.zeroconf, 1500):
            addrs = info.parsed_addresses()
            if addrs:
                found[name] = (addrs[0], info.port or 80)

    def on_change(zeroconf, service_type, name, state_change):
        if state_change in (ServiceStateChange.Added, ServiceStateChange.Updated):
            pending.append(asyncio.ensure_future(resolve(name)))

    browser = AsyncServiceBrowser(azc.zeroconf, [WLED_SERVICE], handlers=[on_change])
    try:
        await asyncio.sleep(seconds)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    finally:
        await browser.async_cancel()
        await azc.async_close()

    async def describe(name: str, host: str, port: int) -> dict:
        addr = host if port == 80 else f"{host}:{port}"
        try:
            return await fetch_info(addr)
        except Exception as exc:
            return {"host": addr, "name": name.split(".")[0], "error": str(exc)}

    return list(await asyncio.gather(*(describe(n, h, p) for n, (h, p) in found.items())))


def resolve_host(host: str) -> str:
    """IP for a host name (DDP is sent to the IP to avoid per-packet DNS lookups)."""
    name = host.split(":")[0]
    try:
        return socket.gethostbyname(name)
    except OSError:
        return name
