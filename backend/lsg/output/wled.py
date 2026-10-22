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
    }


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
