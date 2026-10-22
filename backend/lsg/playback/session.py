"""Playback session: the clock-driven loop that renders frames and distributes them.

Every tick it reads the audio clock, renders the frame and sends it to the browser
preview (WebSocket) and - in live mode - via DDP to the WLED controllers.
"""

import asyncio
import contextlib
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
from lsg.model.calibration import LedCalibration
from lsg.model.project import Project
from lsg.model.show import Show
from lsg.output.curve import duty_to_lightness
from lsg.output.ddp import DdpSender
from lsg.output.pipeline import FrameStats, OutputPipeline
from lsg.output.wled import resolve_host
from lsg.playback.patterns import KINDS, pattern_frame
from lsg.playback.sync import SYNC_SHOW_ID, click_track, sync_features, sync_show
from lsg.render.engine import Renderer

if TYPE_CHECKING:
    from lsg.state import AppState

log = logging.getLogger(__name__)

SYNC_SECONDS = 60.0
MONITOR_SECONDS = 3.0

UI_FPS = 30.0
KEEPALIVE_FPS = 10.0  # live mode while paused: keep WLED in realtime mode


@dataclass
class OutputSettings:
    brightness: float = 1.0  # master brightness, perceived
    audio_latency_ms: float = 0.0  # positive = speakers lag behind (e.g. Bluetooth)

    def to_dict(self) -> dict:
        return {"brightness": self.brightness, "audio_latency_ms": self.audio_latency_ms}


@dataclass
class Loaded:
    project_slug: str
    project: Project
    table: LedTable
    pipeline: OutputPipeline
    hosts: dict[str, str]
    show: Show | None = None
    renderer: Renderer | None = None


@dataclass
class TestPattern:
    fixture_id: str | None  # None = all fixtures
    kind: str = "identify"
    params: dict = field(default_factory=dict)
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
        self.power: FrameStats = FrameStats()
        self.sync: dict | None = None  # {"bpm": .., "previous": show id}
        self.controller_status: dict[str, dict] = {}
        self._monitor_task: asyncio.Task | None = None
        self._power_peak: dict[str, float] = {}
        self._power_peak_t = 0.0
        self.lock = asyncio.Lock()

    # lifecycle
    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop_loop(self) -> None:
        if self._monitor_task:
            self._monitor_task.cancel()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self.player.close()
        self.sender.close()

    # loading
    async def load_project(self, slug: str) -> None:
        """Make a project current (keeps the show if it belongs to the project)."""
        project = self.app.projects.load(slug)
        table = await asyncio.to_thread(build_led_table, project)
        hosts = {c.id: await asyncio.to_thread(resolve_host, c.host) for c in project.controllers}
        show = self.loaded.show if self.loaded and self.loaded.project_slug == slug else None
        self.loaded = Loaded(slug, project, table, OutputPipeline(project, table), hosts, show)
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
            with contextlib.suppress(KeyError):
                duration = self.app.songs.get(show.song_id).duration
        shaders, _ = self.app.show_store(lo.project_slug).load_shaders()
        features = AudioFeatures(analysis, duration)
        lo.renderer = await asyncio.to_thread(Renderer, lo.project, lo.table, show, features, shaders)
        lo.show = show

    async def reload(self, slug: str, show_id: str | None = None) -> None:
        """Hot reload after edits (UI or MCP) without interrupting playback."""
        if not self.loaded or self.loaded.project_slug != slug:
            return
        if self.sync is not None:
            if show_id is None:  # latencies or LEDs changed while syncing: keep the click going
                playing, pos = self.player.playing, self.player.time()
                await self.load_project(slug)
                await self._build_sync_renderer()
                self.player.seek(pos)
                if playing:
                    self.player.play()
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

    # sync test (latency calibration)
    async def _build_sync_renderer(self) -> None:
        lo = self.loaded
        show = sync_show(SYNC_SECONDS)
        lo.renderer = await asyncio.to_thread(
            Renderer, lo.project, lo.table, show, sync_features(self.sync["bpm"], SYNC_SECONDS), {}
        )
        lo.show = show

    async def start_sync(self, bpm: float = 100.0) -> None:
        lo = self.loaded
        if lo is None:
            raise ValueError("no project loaded")
        previous = lo.show.id if lo.show and lo.show.id != SYNC_SHOW_ID else (self.sync or {}).get("previous")
        self.sync = {"bpm": bpm, "previous": previous}
        self.test = None
        self.player.stop()
        await self._build_sync_renderer()
        path = click_track(self.app.data_dir / "sync" / f"click_{bpm:.0f}.wav", bpm, SYNC_SECONDS)
        self.player.load(path)
        self.player.play()
        self._dirty = True
        await self.broadcast_state()

    async def stop_sync(self) -> None:
        if self.sync is None:
            return
        previous = self.sync.get("previous")
        self.sync = None
        self.player.stop()
        if self.loaded:
            await self.load_show(self.loaded.project_slug, previous)
        self._dirty = True

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

    def set_test(self, fixture_id: str | None, enabled: bool, kind: str = "identify", params: dict | None = None) -> None:
        if kind not in KINDS:
            raise ValueError(f"unknown pattern {kind!r}; use one of {KINDS}")
        self.test = TestPattern(fixture_id, kind, params or {}) if enabled else None
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
            "test": {"fixture": self.test.fixture_id, "kind": self.test.kind, "params": self.test.params} if self.test else None,
            "led_count": lo.table.count if lo else 0,
            "fps": self.fps,
            "render_ms": round(self.render_ms, 2),
            "clip_errors": dict(r.errors) if r else {},
            "output": self.output.to_dict(),
            "power": {
                "total_ma": round(self.power.total_ma),
                "total_requested_ma": round(self.power.total_requested_ma),
                "total_budget_ma": lo.project.power.total_budget_ma if lo else None,
                "controllers": self.power.controllers,
                "peak_ma": {k: round(v) for k, v in self._power_peak.items()},
            },
            "controller_errors": dict(self.sender.errors),
            "controller_status": self.controller_status,
            "sync": self.sync,
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
    def render_at(self, t: float) -> tuple[np.ndarray, bool] | None:
        """Frame at song time t and whether it holds raw PWM values (calibration patterns)."""
        lo = self.loaded
        if lo is None:
            return None
        if self.test is not None:
            ids = [self.test.fixture_id] if self.test.fixture_id else lo.table.fixture_ids
            return pattern_frame(self.test.kind, lo.table, ids, self.test.params, time.monotonic() - self.test.started)
        if lo.renderer is None:
            return np.zeros((lo.table.count, 3), np.float32), False
        return lo.renderer.render(t), False

    def _output(self, frame_for, raw: bool, send: bool) -> None:
        lo = self.loaded
        outputs, stats = lo.pipeline.encode_all(frame_for, self.output.brightness, raw=raw)
        self.power = stats
        now = time.monotonic()
        if now - self._power_peak_t > 3.0:
            self._power_peak, self._power_peak_t = {}, now
        for cid, c in stats.controllers.items():
            self._power_peak[cid] = max(self._power_peak.get(cid, 0.0), c["requested_ma"])
        self._power_peak["total"] = max(self._power_peak.get("total", 0.0), stats.total_requested_ma)
        if not send:
            return
        for out in outputs:
            c = out.plan.controller
            if out.data:
                self.sender.send(lo.hosts.get(c.id, c.host), c.port, out.data, c.rgbw)

    @staticmethod
    def ui_message(t: float, frame: np.ndarray, raw: bool = False) -> bytes:
        if raw:  # show raw PWM roughly as it will look
            frame = duty_to_lightness(frame / 255.0, LedCalibration())
        rgb = (np.clip(frame, 0, 1) * 255 + 0.5).astype(np.uint8)
        return struct.pack("<dI", t, len(frame)) + rgb.tobytes()

    async def _monitor_loop(self) -> None:
        """Poll the WLED controllers of the loaded project while someone is looking or live mode is on."""
        from lsg.output.wled import controller_status

        while True:
            await asyncio.sleep(MONITOR_SECONDS)
            lo = self.loaded
            if lo is None or not lo.pipeline.plans or not (self.clients or self.mode == "live"):
                continue
            try:
                results = await asyncio.gather(
                    *(
                        controller_status(p.controller.host, p.pixel_count, self.fps, self.mode == "live")
                        for p in lo.pipeline.plans
                    )
                )
                self.controller_status = {p.controller.id: r for p, r in zip(lo.pipeline.plans, results, strict=False)}
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("controller monitor failed")

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
        if self.sync is not None and self.player.finished:  # loop the click track
            self.player.seek(0)
            self.player.play()
        active = self.player.playing or self.test is not None
        if not active and not self._dirty and not (self.mode == "live" and now - self._last_live >= 1 / KEEPALIVE_FPS):
            if now - self._last_state > 1.0:
                self._last_state = now
                await self.broadcast_state()
            return
        t = self.show_time()
        start = time.perf_counter()
        result = self.render_at(t)
        self.render_ms = 0.9 * self.render_ms + 0.1 * (time.perf_counter() - start) * 1000
        if result is None:
            return
        frame, raw = result
        if lo.pipeline.plans:
            live = self.mode == "live"
            frames: dict[float, np.ndarray] = {0.0: frame}

            def frame_for(controller):
                dt = controller.latency_ms / 1000.0
                if dt not in frames:
                    frames[dt] = self.render_at(t + dt)[0] if active and self.test is None else frame
                return frames[dt]

            self._output(frame_for, raw, send=live)
            if live:
                self._last_live = now
        if self.clients and (self._dirty or now - self._last_ui >= 1 / UI_FPS - 1e-3):
            self._last_ui = now
            await self._send_all(self.ui_message(t, frame, raw))
        if self._dirty or now - self._last_state > 0.5:
            self._last_state = now
            await self.broadcast_state()
        self._dirty = False
