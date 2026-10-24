"""Phone remote: play / pause, jump, brightness, shows and live cues from a phone in the same Wi-Fi.

The app itself only listens on localhost. The remote is a separate small server on all network
interfaces (port REMOTE_PORT) that offers nothing but these few actions, and every request needs
the random key from the QR code. Cues from the phone are laid over the running show for a moment
(Renderer.add_live) - they are not written into the show.
"""

import asyncio
import contextlib
import hmac
import logging
import secrets
import socket
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from lumora.model.show import Clip, Target

if TYPE_CHECKING:
    from lumora.state import AppState

log = logging.getLogger(__name__)
REMOTE_PORT = 8010
PAGE = Path(__file__).parent / "static" / "remote.html"  # the phone page (plain HTML + JS)

# one-shot cues (like the cue pads in the show editor): effect, params, target, length in beats
CUES: dict[str, tuple[str, dict, dict, float]] = {
    "flash": ("pulse", {"decay": 0.3, "trigger": "once"}, {}, 2),
    "room": ("pulse", {"decay": 0.6, "trigger": "once"}, {"view": "indirect"}, 3),
    "ring": ("ripple", {"center": "viewer", "speed": 5, "width": 0.5, "decay": 1.6, "trigger": "once"}, {}, 4),
    "up": ("sweep", {"axis": "z", "width": 0.15, "tail": 0.4, "trigger": "once"}, {}, 2),
    "across": ("sweep", {"axis": "azimuth", "width": 0.12, "tail": 0.4, "trigger": "once"}, {"view": "direct"}, 2),
    "sparkle": ("sparkle", {"density": 0.12, "decay": 0.12, "rate": 24}, {}, 2),
}


def lan_address() -> str:
    """This PC's address in the local network (no packet is sent)."""
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))  # TEST-NET address: only picks the outgoing interface
        return s.getsockname()[0]
    return socket.gethostbyname(socket.gethostname())


def new_key() -> str:
    return secrets.token_urlsafe(9)


def cue_clip(kind: str, t: float, bpm: float, color: str) -> Clip:
    effect, params, target, beats = CUES[kind]
    beat = 60.0 / bpm if bpm > 0 else 0.5
    p = {**params, **({"palette": [color]} if effect == "sparkle" else {"color": color})}
    return Clip(start=round(t, 3), end=round(t + beats * beat, 3), effect=effect, params=p, target=Target(**target), blend="add")


class Action(BaseModel):
    action: str  # play | pause | toggle | seek | brightness | cue | show
    value: float | None = None
    kind: str | None = None
    color: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    show: str | None = None


def create_remote_app(st: "AppState") -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def check(k: str) -> None:
        key = st.settings.get("remote_key") or ""
        if not key or not hmac.compare_digest(k.encode(), key.encode()):
            raise HTTPException(403, "wrong or missing key - scan the QR code in the app again")

    def state() -> dict:
        s = st.session
        lo = s.loaded
        shows = st.show_store(lo.project_slug).list() if lo else []
        pb = s.state()
        return {
            "show": pb.get("show"),
            "show_name": pb.get("show_name"),
            "playing": pb.get("playing"),
            "position": pb.get("position"),
            "duration": pb.get("duration"),
            "mode": pb.get("mode"),
            "brightness": s.output.brightness,
            "shows": [{"id": x.id, "name": x.name} for x in shows if x.id != "__sync__"],
        }

    @app.get("/", response_class=HTMLResponse)
    def page(k: str = Query("")):
        check(k)
        return HTMLResponse(PAGE.read_text(encoding="utf-8").replace("__KEY__", k))

    @app.get("/state")
    def get_state(k: str = Query("")):
        check(k)
        return state()

    @app.post("/action")
    async def act(body: Action, request: Request, k: str = Query("")):
        check(k)
        s = st.session
        if body.action in ("play", "pause", "toggle"):
            playing = s.player.playing
            if body.action == "play" or (body.action == "toggle" and not playing):
                s.play()
            else:
                s.pause()
        elif body.action == "seek" and body.value is not None:
            s.seek(max(0.0, min(s.show_time() + body.value, s.player.duration or 1e9)))
        elif body.action == "brightness" and body.value is not None:
            s.output.brightness = max(0.0, min(1.0, body.value))
            st.save_settings()
            s.mark_dirty()
        elif body.action == "cue" and body.kind in CUES:
            lo = s.loaded
            if lo is None or lo.renderer is None:
                raise HTTPException(409, "no show loaded")
            bpm = lo.renderer.features.bpm or 120.0
            lo.renderer.add_live(cue_clip(body.kind, s.show_time(), bpm, body.color))
            s.mark_dirty()
        elif body.action == "show" and body.show:
            lo = s.loaded
            if lo is None:
                raise HTTPException(409, "no project open")
            try:
                await s.load_show(lo.project_slug, body.show)
            except KeyError:
                raise HTTPException(404, "unknown show") from None
        else:
            raise HTTPException(422, "unknown action")
        await s.broadcast_state()
        return state()

    return app


class RemoteServer:
    """Runs the remote app on all interfaces while it is switched on."""

    def __init__(self, st: "AppState"):
        self.st = st
        self.server = None
        self.task: asyncio.Task | None = None
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    async def start(self, port: int = REMOTE_PORT) -> None:
        import uvicorn

        if self.running:
            return
        self.error = None
        config = uvicorn.Config(create_remote_app(self.st), host="0.0.0.0", port=port, log_level="warning", lifespan="off")
        self.server = uvicorn.Server(config)
        self.server.install_signal_handlers = lambda: None  # the main app owns the signals
        self.task = asyncio.create_task(self._serve())
        for _ in range(50):  # wait until it listens (or failed)
            if self.server.started or self.task.done():
                break
            await asyncio.sleep(0.05)

    async def _serve(self) -> None:
        try:
            await self.server.serve()
        except (OSError, SystemExit) as exc:
            self.error = f"Port {REMOTE_PORT} ist belegt oder gesperrt ({exc})"
            log.warning("remote server failed: %s", exc)

    async def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(self.task, timeout=3)
        self.server = self.task = None
