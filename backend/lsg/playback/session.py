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
from lsg.output.link import OutputLink, set_timer_resolution
from lsg.output.pipeline import FrameStats, OutputPipeline
from lsg.output.wled import recommended_fps, resolve_host
from lsg.playback.patterns import KINDS, pattern_frame
from lsg.playback.sync import SYNC_SHOW_ID, click_track, sync_features, sync_show
from lsg.render.engine import Renderer

if TYPE_CHECKING:
    from lsg.state import AppState

log = logging.getLogger(__name__)

SYNC_SECONDS = 60.0
MONITOR_SECONDS = 3.0
CONFIG_SECONDS = 120.0  # re-read a controller's LED setup (/json/cfg) this often

UI_FPS = 30.0
IDLE_SECONDS = 0.05  # loop wake-up when nothing is due (state broadcasts, finished sync track)


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
        self._wake = asyncio.Event()
        self._dirty_gen = 0
        self._dirty = True
        self._task: asyncio.Task | None = None
        self._ui_next = 0.0
        self._last_state = 0.0
        self.links: dict[str, OutputLink] = {}  # controller id -> send schedule
        self.wled_config: dict[str, dict] = {}  # host -> LED setup read from /json/cfg
        self._config_time: dict[str, float] = {}
        self.speed_testing: set[str] = set()  # controllers currently fed by a speed test
        self.render_ms = 0.0
        self.power: FrameStats = FrameStats()
        self.sync: dict | None = None  # {"bpm": .., "previous": show id}
        self.live_input = None  # LiveInput / FileInput while the live input mode runs
        self._live_previous: str | None = None
        self.controller_status: dict[str, dict] = {}
        self._monitor_task: asyncio.Task | None = None
        self._power_peak: dict[str, float] = {}
        self._power_peak_t = 0.0
        self.lock = asyncio.Lock()

    @property
    def _dirty(self) -> bool:
        return self._dirty_flag

    @_dirty.setter
    def _dirty(self, value: bool) -> None:
        self._dirty_flag = value
        if value:
            self._dirty_gen += 1
            self._wake.set()  # react at once instead of at the next scheduled frame

    # lifecycle
    def start(self) -> None:
        from lsg.output.wled import warm_client

        set_timer_resolution(True)
        self._warm_task = asyncio.create_task(warm_client())
        self._task = asyncio.create_task(self._loop())
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop_loop(self) -> None:
        if self.live_input is not None:
            self.live_input.close()
            self.live_input = None
        if self._monitor_task:
            self._monitor_task.cancel()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self.player.close()
        self.sender.close()
        set_timer_resolution(False)

    # loading
    async def load_project(self, slug: str) -> None:
        """Make a project current (keeps the show if it belongs to the project)."""
        project = self.app.projects.load(slug)
        table = await asyncio.to_thread(build_led_table, project)
        hosts = {c.id: await asyncio.to_thread(resolve_host, c.host) for c in project.controllers}
        show = self.loaded.show if self.loaded and self.loaded.project_slug == slug else None
        self.loaded = Loaded(slug, project, table, OutputPipeline(project, table), hosts, show)
        self._sync_links()
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
        if self.live_input is not None:
            lo = self.loaded
            if show_id is None:
                await self.load_project(slug)
            show_id = show_id or (lo.show.id if lo.show else None)
            if show_id and self.loaded.show and self.loaded.show.id == show_id:
                await self._build_live_renderer(self.app.show_store(slug).get(show_id))
            self._dirty = True
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

    # live input (microphone, no pre-analysis)
    async def _build_live_renderer(self, show: Show) -> None:
        lo = self.loaded
        shaders, _ = self.app.show_store(lo.project_slug).load_shaders()
        lo.renderer = await asyncio.to_thread(Renderer, lo.project, lo.table, show, self.live_input.features, shaders)
        lo.show = show

    async def start_live_input(self, show_id: str | None, device=None, file=None) -> None:
        from lsg.audio.live import FileInput, LiveInput
        from lsg.render.autoshow import live_show

        lo = self.loaded
        if lo is None:
            raise ValueError("no project loaded")
        await self.stop_live_input(restore=False)
        if self.sync is not None:
            await self.stop_sync()
        self._live_previous = lo.show.id if lo.show else None
        store = self.app.show_store(lo.project_slug)
        if show_id is None:
            existing = next((s for s in store.list() if s.name == "Live (Mikrofon)"), None)
            show = existing or live_show()
            if existing is None:
                store.save(show, "system")
        else:
            show = store.get(show_id)
        self.player.stop()
        self.test = None
        self.live_input = await asyncio.to_thread(FileInput, file) if file else await asyncio.to_thread(LiveInput, device)
        await self._build_live_renderer(show)
        self._dirty = True
        await self.broadcast_state()

    async def stop_live_input(self, restore: bool = True) -> None:
        if self.live_input is None:
            return
        self.live_input.close()
        self.live_input = None
        if restore and self.loaded:
            await self.load_show(self.loaded.project_slug, self._live_previous)
        self._dirty = True

    def live_state(self) -> dict | None:
        li = self.live_input
        if li is None:
            return None
        f = li.features
        return {
            "device": li.device_name,
            "bpm": round(f.bpm, 1),
            "levels": {k: round(v, 3) for k, v in f.levels.items()},
            "time": round(f.t, 2),
        }

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
        if self.live_input is not None:
            r = self.loaded.renderer if self.loaded else None
            loop = r.duration if r and r.duration > 0 else 240.0
            return self.live_input.time() % loop
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
            "links": {cid: {"rate": link.rate, "sent_fps": round(link.sent_fps(), 1)} for cid, link in self.links.items()},
            "speed_testing": sorted(self.speed_testing),
            "controller_status": self.controller_status,
            "sync": self.sync,
            "live_input": self.live_state(),
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

    # live output
    def rate_for(self, controller) -> float:
        """Frames per second for a controller: its manual setting or what its LED setup can show."""
        if controller.max_fps:
            return float(controller.max_fps)
        cfg = self.wled_config.get(controller.host)
        return recommended_fps(cfg.get("max_fps") if cfg else None, self.fps)

    def _sync_links(self) -> None:
        lo = self.loaded
        plans = lo.pipeline.plans if lo else []
        links = {}
        for p in plans:
            c = p.controller
            if not p.pixel_count:  # nothing mapped: nothing to send
                continue
            link = self.links.get(c.id) or OutputLink(self.rate_for(c), next_due=time.perf_counter())
            link.rate = self.rate_for(c)
            links[c.id] = link
        self.links = links

    def _output(self, frame_for, raw: bool, due: set[str], now: float, force: bool) -> None:
        lo = self.loaded
        outputs, stats = lo.pipeline.encode_all(frame_for, self.output.brightness, raw=raw, only=due)
        self.power = stats
        if now - self._power_peak_t > 3.0:
            self._power_peak, self._power_peak_t = {}, now
        for cid, c in stats.controllers.items():
            self._power_peak[cid] = max(self._power_peak.get(cid, 0.0), c["requested_ma"])
        self._power_peak["total"] = max(self._power_peak.get("total", 0.0), stats.total_requested_ma)
        for out in outputs:
            c = out.plan.controller
            link = self.links.get(c.id)
            if c.id in due and link is not None and out.data and link.offer(out.data, now, force):
                self.sender.send(lo.hosts.get(c.id, c.host), c.port, out.data, c.rgbw)

    async def speed_test(self, controller_id: str) -> dict:
        """Find out how many frames per second a controller really shows.

        Phase 1 floods it with a moving pattern (faster than any WLED can show) and reads the
        frame rate WLED reports. Phase 2 sends at a rate it can manage; frames missing there
        were lost on the way (WiFi)."""
        from lsg.output.wled import WLED_MAX_FPS, fetch_config, fetch_info

        lo = self.loaded
        plan = next((p for p in lo.pipeline.plans if p.controller.id == controller_id), None) if lo else None
        if plan is None:
            raise KeyError(f"controller {controller_id}")
        if plan.pixel_count == 0:
            raise ValueError("Diesem Controller sind keine LEDs zugeordnet")
        if controller_id in self.speed_testing:
            raise ValueError("Messung läuft bereits")
        c = plan.controller
        host = lo.hosts.get(c.id, c.host)
        x = np.arange(plan.pixel_count, dtype=np.float32) / plan.pixel_count

        async def run(fps: float, seconds: float) -> tuple[float, dict]:
            end = time.perf_counter() + seconds

            async def send() -> int:
                i, nxt = 0, time.perf_counter()
                while time.perf_counter() < end:
                    h = (2 * x + i / 30.0) % 1.0  # moving, dim rainbow
                    rgb = np.stack([np.sin(2 * np.pi * (h + k / 3)) * 0.5 + 0.5 for k in range(3)], 1) * 48
                    if c.rgbw:
                        rgb = np.concatenate([rgb, np.zeros((len(x), 1), np.float32)], 1)
                    self.sender.send(host, c.port, rgb.astype(np.uint8).tobytes(), c.rgbw)
                    i += 1
                    nxt += 1.0 / fps
                    await asyncio.sleep(max(0.0, nxt - time.perf_counter()))
                return i

            task = asyncio.create_task(send())
            try:
                await asyncio.sleep(seconds - 0.8)  # WLED averages its fps over a few frames
                info = await fetch_info(c.host, timeout=1.5)
            finally:
                sent = await task
            return sent / seconds, info

        self.speed_testing.add(c.id)
        self._dirty = True
        try:
            with contextlib.suppress(Exception):
                self.wled_config[c.host] = await fetch_config(c.host)
                self._config_time[c.host] = time.monotonic()
            _, info = await run(80.0, 3.0)
            if not info.get("live"):
                raise ValueError("WLED übernimmt keine Echtzeitdaten (in WLED unter Sync „Receive UDP realtime“ aktivieren)")
            measured = float(info.get("fps") or 0)
            rate = float(round(max(10.0, min(40.0, measured * 0.8))))
            sent, info2 = await run(rate, 3.5)
            shown = min(float(info2.get("fps") or 0), round(sent))  # WLED's average lags behind phase 1
            loss = max(0.0, 1.0 - shown / sent) if sent else 0.0
        finally:
            self.speed_testing.discard(c.id)
            self._dirty = True
        cfg = self.wled_config.get(c.host)
        return {
            "controller": c.id,
            "measured_fps": measured,
            "estimated_fps": cfg.get("max_fps") if cfg else None,
            "test_fps": rate,
            "shown_fps": shown,
            "loss_pct": round(loss * 100) if loss > 0.08 else 0,  # WLED rounds its fps: ignore tiny gaps
            "recommended_fps": recommended_fps(measured if measured < WLED_MAX_FPS else None, self.fps),
            "rssi": info2.get("rssi"),
        }

    @staticmethod
    def ui_message(t: float, frame: np.ndarray, raw: bool = False) -> bytes:
        if raw:  # show raw PWM roughly as it will look
            frame = duty_to_lightness(frame / 255.0, LedCalibration())
        rgb = (np.clip(frame, 0, 1) * 255 + 0.5).astype(np.uint8)
        return struct.pack("<dI", t, len(frame)) + rgb.tobytes()

    async def _monitor_loop(self) -> None:
        """Poll the WLED controllers of the loaded project while someone is looking or live mode is on."""
        from lsg.output.wled import controller_status, fetch_config

        async def config(host: str) -> dict | None:
            now = time.monotonic()
            if now - self._config_time.get(host, -1e9) > CONFIG_SECONDS:
                self._config_time[host] = now
                try:
                    self.wled_config[host] = await fetch_config(host)
                except Exception:  # unreachable or an old WLED: retry sooner
                    self._config_time[host] = now - CONFIG_SECONDS + 15
            return self.wled_config.get(host)

        async def status(p) -> dict:
            c = p.controller
            cfg = await config(c.host)
            link = self.links.get(c.id)
            sent = link.sent_fps() if link and self.mode == "live" else 0.0
            st = await controller_status(c.host, p.pixel_count, sent, self.mode == "live", cfg)
            st["rate"] = self.rate_for(c)
            st["rate_auto"] = c.max_fps is None
            return st

        while True:
            await asyncio.sleep(MONITOR_SECONDS)
            lo = self.loaded
            if lo is None or not lo.pipeline.plans or not (self.clients or self.mode == "live"):
                continue
            try:
                results = await asyncio.gather(*(status(p) for p in lo.pipeline.plans))
                self.controller_status = {p.controller.id: r for p, r in zip(lo.pipeline.plans, results, strict=False)}
                self._sync_links()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("controller monitor failed")

    async def _loop(self) -> None:
        while True:
            try:
                wake = await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("playback tick failed")
                wake = time.perf_counter() + 1.0 / self.fps
            delay = wake - time.perf_counter()
            if delay > 0 and not self._dirty:
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), delay)
            else:
                await asyncio.sleep(0)

    async def _tick(self) -> float:
        """Render and distribute one frame if any consumer is due; returns the next wake-up time.

        Consumers: each live controller on its own schedule, the browser preview at UI_FPS.
        One render serves everything due at the same moment."""
        now = time.perf_counter()
        lo = self.loaded
        if lo is None:
            return now + IDLE_SECONDS
        if self.sync is not None and self.player.finished:  # loop the click track
            self.player.seek(0)
            self.player.play()
        active = self.player.playing or self.test is not None or self.live_input is not None
        dirty, gen = self._dirty, self._dirty_gen
        changing = active or dirty
        live = self.mode == "live" and bool(lo.pipeline.plans)
        links = {cid: link for cid, link in self.links.items() if cid not in self.speed_testing} if live else {}
        due = {cid for cid, link in links.items() if dirty or link.needs_frame(now, changing)}
        ui = bool(self.clients) and (dirty or (active and now >= self._ui_next - 0.003))

        if due or ui:
            t = self.show_time()
            start = time.perf_counter()
            result = self.render_at(t)
            self.render_ms = 0.9 * self.render_ms + 0.1 * (time.perf_counter() - start) * 1000
            if result is not None:
                frame, raw = result
                if lo.pipeline.plans:
                    frames: dict[float, np.ndarray] = {0.0: frame}

                    def frame_for(controller):
                        dt = controller.latency_ms / 1000.0
                        if dt not in frames:
                            frames[dt] = self.render_at(t + dt)[0] if active and self.test is None else frame
                        return frames[dt]

                    self._output(frame_for, raw, due, now, force=dirty)
                if ui:
                    self._ui_next += 1.0 / UI_FPS
                    if self._ui_next < now:
                        self._ui_next = now + 1.0 / UI_FPS
                    await self._send_all(self.ui_message(t, frame, raw))
        if dirty or now - self._last_state > (0.5 if active else 1.0):
            self._last_state = now
            await self.broadcast_state()
        if dirty and self._dirty_gen == gen:  # keep changes that arrived while this tick awaited
            self._dirty = False

        wake = [now + IDLE_SECONDS]
        wake += [link.next_wake(now, changing) for link in links.values()]
        if self.clients and active:
            wake.append(self._ui_next)
        return min(wake)
