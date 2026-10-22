"""WLED HTTP JSON API and mDNS discovery."""

import asyncio
import socket

import httpx
from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

WLED_SERVICE = "_wled._tcp.local."


async def fetch_info(host: str, timeout: float = 2.0) -> dict:
    """Summary of a WLED device from /json/info."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(f"http://{host}/json/info")
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


# rough DDP limits at ~50 FPS (one output); more LEDs lower the achievable frame rate
LED_LIMITS = {"esp8266": 600, "esp32": 1500}


async def controller_status(host: str, pixels: int, sending_fps: float, live: bool) -> dict:
    """Reachability and health of one controller with human readable warnings."""
    try:
        info = await fetch_info(host, timeout=1.5)
    except Exception as exc:
        return {"ok": False, "error": f"nicht erreichbar ({type(exc).__name__})", "warnings": []}
    warnings = []
    if info["led_count"] and pixels > info["led_count"]:
        warnings.append(f"WLED hat nur {info['led_count']} LEDs konfiguriert, zugeordnet sind {pixels}")
    arch = str(info.get("arch") or "").lower()
    limit = next((v for k, v in LED_LIMITS.items() if arch.startswith(k)), None)
    if limit and pixels > limit:
        warnings.append(f"{pixels} LEDs an einem {arch.upper()}: über ca. {limit} sinkt die Bildrate (Strips auf mehrere Controller verteilen)")
    if info.get("rssi") is not None and info["rssi"] < -75:
        warnings.append(f"schwaches WLAN ({info['rssi']} dBm): Pakete können verloren gehen")
    if live and info.get("fps") and info["fps"] < 0.8 * sending_fps:
        warnings.append(f"WLED zeigt {info['fps']} FPS bei {sending_fps:.0f} gesendeten: Frames gehen verloren oder der Controller ist überlastet")
    return {"ok": True, "info": info, "warnings": warnings}


async def set_state(host: str, state: dict, timeout: float = 2.0) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"http://{host}/json/state", json=state)
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
