"""Playback session: the clock-driven loop that renders frames and distributes them.

Every tick it reads the audio clock, renders the frame and sends it to the browser
preview (WebSocket) and - in live mode - via DDP to the WLED controllers.
"""

import asyncio
import json
import logging
import struct
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from fastapi import WebSocket

from lsg.audio.features import AudioFeatures
from lsg.geometry.led_table import LedTable, build_led_table
from lsg.model.project import Project
from lsg.model.show import Show
from lsg.output.ddp import DdpSender
from lsg.output.mapper import ControllerPlan, encode, plan_controllers
from lsg.output.wled import resolve_host
from lsg.render.engine import Renderer

if TYPE_CHECKING:
    from lsg.state import AppState

log = logging.getLogger(__name__)

UI_FPS = 30.0
KEEPALIVE_FPS = 10.0  # live mode while paused: keep WLED in realtime mode


@dataclass
class OutputSettings:
    gamma: float = 2.2
    brightness: float = 1.0
    audio_latency_ms: float = 0.0  # positive = speakers lag behind (e.g. Bluetooth)


@dataclass
class Loaded:
    project_slug: str
    project: Project
    table: LedTable
    plans: list[ControllerPlan]
    hosts: dict[str, str]
    show: Show | None = None
    renderer: Renderer | None = None


@dataclass
class TestPattern:
    fixture_id: str | None  # None = all fixtures
    started: float = field(default_factory=time.monotonic)


class PlaybackSession:
    def __init__(self, app: "AppState", player, fps: float):
        self.app = app
        self.player = player
        self.fps = fps
        self.mode = "preview"  # or "live"
        self.output = OutputSettings()
        self.loaded: Loaded | None = None
        self.test: TestPattern | None = None
        self.clients: set[WebSocket] = set()
        self.sender = DdpSender()
        self._dirty = True
        self._task: asyncio.Task | None = None
        self._last_ui = 0.0
        self._last_live = 0.0
        self._last_state = 0.0
        self.render_ms = 0.0
        self.lock = asyncio.Lock()

    # lifecycle
    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop_loop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.player.close()
        self.sender.close()

    # loading
    async def load_project(self, slug: str) -> None:
        """Make a project current (keeps the show if it belongs to the project)."""
        project = self.app.projects.load(slug)
        table = await asyncio.to_thread(build_led_table, project)
        hosts = {c.id: await asyncio.to_thread(resolve_host, c.host) for c in project.controllers}
        show = self.loaded.show if self.loaded and self.loaded.project_slug == slug else None
        self.loaded = Loaded(slug, project, table, plan_controllers(project, table), hosts, show)
        if show is not None:
            await self._build_renderer(show)
        self._dirty = True
        await self.broadcast_state()

    async def load_show(self, slug: str, show_id: str | None) -> None:
        if not self.loaded or self.loaded.project_slug != slug:
            await self.load_project(slug)
        self.player.stop()
        if show_id is None:
            self.loaded.show = None
            self.loaded.renderer = None
            self.player.load(None, 0.0)
        else:
            show = self.app.show_store(slug).get(show_id)
            await self._build_renderer(show)
            song_path = self._song_path(show)
            self.player.load(song_path, None if song_path else self.loaded.renderer.duration)
        self._dirty = True
        await self.broadcast_state()

    def _song_path(self, show: Show):
        if show.song_id:
            try:
                return self.app.songs.audio_path(show.song_id)
            except KeyError:
                return None
        return None

    async def _build_renderer(self, show: Show) -> None:
        lo = self.loaded
        analysis = self.app.songs.analysis(show.song_id) if show.song_id else None
        duration = None
        if show.song_id and analysis is None:
            try:
                duration = self.app.songs.get(show.song_id).duration
            except KeyError:
                pass
        shaders, _ = self.app.show_store(lo.project_slug).load_shaders()
        features = AudioFeatures(analysis, duration)
        lo.renderer = await asyncio.to_thread(Renderer, lo.project, lo.table, show, features, shaders)
        lo.show = show

    async def reload(self, slug: str, show_id: str | None = None) -> None:
        """Hot reload after edits (UI or MCP) without interrupting playback."""
        if not self.loaded or self.loaded.project_slug != slug:
            return
        if show_id is None:
            # project or shaders changed
            playing, pos = self.player.playing, self.player.time()
            show = self.loaded.show
            await self.load_project(slug)
            if show is not None:
                try:
                    await self._build_renderer(self.app.show_store(slug).get(show.id))
                except KeyError:
                    self.loaded.show = self.loaded.renderer = None
            if playing:
                self.player.seek(pos)
        elif self.loaded.show and self.loaded.show.id == show_id:
            try:
                show = self.app.show_store(slug).get(show_id)
            except KeyError:
                self.loaded.show = self.loaded.renderer = None
            else:
                song_changed = show.song_id != self.loaded.show.song_id
                await self._build_renderer(show)
                if song_changed:
                    self.player.stop()
                    path = self._song_path(show)
                    self.player.load(path, None if path else self.loaded.renderer.duration)
        self._dirty = True
        await self.broadcast_state()

    # transport
    def play(self) -> None:
        if self.loaded and self.loaded.renderer:
            if self.player.finished:
                self.player.seek(0)
            self.test = None
            self.player.play()

    def pause(self) -> None:
        self.player.pause()
        self._dirty = True

    def seek(self, t: float) -> None:
        self.player.seek(t)
        self._dirty = True

    def stop(self) -> None:
        self.player.stop()
        self._dirty = True

    def set_mode(self, mode: str) -> None:
        if mode not in ("preview", "live"):
            raise ValueError("mode must be preview or live")
        self.mode = mode
        self._dirty = True

    def set_test(self, fixture_id: str | None, enabled: bool) -> None:
        self.test = TestPattern(fixture_id) if enabled else None
        if enabled:
            self.player.pause()
        self._dirty = True

    def show_time(self) -> float:
        return max(0.0, self.player.time() - self.output.audio_latency_ms / 1000.0)

    # state
    def state(self) -> dict:
        lo = self.loaded
        r = lo.renderer if lo else None
        return {
            "type": "state",
            "project": lo.project_slug if lo else None,
            "show": lo.show.id if lo and lo.show else None,
            "show_name": lo.show.name if lo and lo.show else None,
            "song": lo.show.song_id if lo and lo.show else None,
            "playing": self.player.playing,
            "position": round(self.show_time(), 3),
            "duration": round(self.player.duration or (r.duration if r else 0.0), 3),
            "mode": self.mode,
            "test": {"fixture": self.test.fixture_id} if self.test else None,
            "led_count": lo.table.count if lo else 0,
            "fps": self.fps,
            "render_ms": round(self.render_ms, 2),
            "clip_errors": dict(r.errors) if r else {},
            "output": {
                "gamma": self.output.gamma,
                "brightness": self.output.brightness,
                "audio_latency_ms": self.output.audio_latency_ms,
            },
            "controller_errors": dict(self.sender.errors),
        }

    async def broadcast_state(self) -> None:
        await self._send_all(json.dumps(self.state()))

    async def broadcast_event(self, event: dict) -> None:
        await self._send_all(json.dumps({"type": "event", **event}))

    async def _send_all(self, msg: str | bytes) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                if isinstance(msg, bytes):
                    await ws.send_bytes(msg)
                else:
                    await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    # frames
    def _test_frame(self, now: float) -> np.ndarray:
        lo = self.loaded
        frame = np.zeros((lo.table.count, 3), np.float32)
        blink = 1.0 if (now - self.test.started) % 1.0 < 0.6 else 0.25
        ids = [self.test.fixture_id] if self.test.fixture_id else lo.table.fixture_ids
        for fid in ids:
            if fid not in lo.table.fixture_ids:
                continue
            sl = lo.table.fixture_slice(fid)
            frame[sl] = [0.0, 0.0, 0.6 * blink]
            frame[sl.start] = [0.0, 1.0, 0.0]  # data input = green
            frame[sl.stop - 1] = [1.0, 0.0, 0.0]  # end = red
        return frame

    def render_at(self, t: float) -> np.ndarray | None:
        lo = self.loaded
        if lo is None:
            return None
        if self.test is not None:
            return self._test_frame(time.monotonic())
        if lo.renderer is None:
            return np.zeros((lo.table.count, 3), np.float32)
        return lo.renderer.render(t)

    def _send_live(self, frame_fn) -> None:
        lo = self.loaded
        by_latency: dict[float, np.ndarray] = {}
        for plan in lo.plans:
            lat = plan.controller.latency_ms
            if lat not in by_latency:
                by_latency[lat] = frame_fn(lat / 1000.0)
            data = encode(by_latency[lat], plan, self.output.gamma, self.output.brightness)
            if data:
                self.sender.send(lo.hosts.get(plan.controller.id, plan.controller.host), plan.controller.port, data, plan.controller.rgbw)

    @staticmethod
    def ui_message(t: float, frame: np.ndarray) -> bytes:
        rgb = (np.clip(frame, 0, 1) * 255 + 0.5).astype(np.uint8)
        return struct.pack("<dI", t, len(frame)) + rgb.tobytes()

    async def _loop(self) -> None:
        period = 1.0 / self.fps
        next_tick = time.perf_counter()
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("playback tick failed")
            next_tick += period
            delay = next_tick - time.perf_counter()
            if delay < -0.25:  # fell far behind (debugger, sleep): resync
                next_tick = time.perf_counter()
                delay = 0
            await asyncio.sleep(max(0.0, delay))

    async def _tick(self) -> None:
        now = time.perf_counter()
        lo = self.loaded
        if lo is None:
            return
        active = self.player.playing or self.test is not None
        if not active and not self._dirty and not (self.mode == "live" and now - self._last_live >= 1 / KEEPALIVE_FPS):
            if now - self._last_state > 1.0:
                self._last_state = now
                await self.broadcast_state()
            return
        t = self.show_time()
        start = time.perf_counter()
        frame = self.render_at(t)
        self.render_ms = 0.9 * self.render_ms + 0.1 * (time.perf_counter() - start) * 1000
        if frame is None:
            return
        if self.mode == "live" and lo.plans:
            if active and self.test is None:
                self._send_live(lambda dt: frame if dt == 0 else self.render_at(t + dt))
            else:
                self._send_live(lambda dt: frame)
            self._last_live = now
        if self.clients and (self._dirty or now - self._last_ui >= 1 / UI_FPS - 1e-3):
            self._last_ui = now
            await self._send_all(self.ui_message(t, frame))
        if self._dirty or now - self._last_state > 0.5:
            self._last_state = now
            await self.broadcast_state()
        self._dirty = False
