"""Application state shared by the REST API, the WebSocket and the MCP server."""

import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from lsg import config
from lsg.ai_agent import AI_MODELS, DEFAULT_MODEL, AgentManager
from lsg.audio.library import SongLibrary
from lsg.audio.player import create_player
from lsg.playback.session import PlaybackSession
from lsg.storage.project_store import ProjectStore, atomic_write_text
from lsg.storage.show_store import ShowStore

log = logging.getLogger(__name__)


class AppState:
    def __init__(self, data_dir: Path, audio_backend: str, fps: float):
        self.data_dir = Path(data_dir)
        self.projects = ProjectStore(self.data_dir / "projects")
        self.settings: dict = {
            "beat_tracker": "auto",
            "shader_isolation": True,
            "ai_model": DEFAULT_MODEL,
            "flash_limit": 3.0,  # large flashes per second at most (0 = off), see lsg.render.safety
            "safety_ack": False,  # the photosensitivity warning was confirmed
        }
        self.songs = SongLibrary(
            self.data_dir / "songs",
            lambda: self.settings.get("beat_tracker", "auto"),
            lambda: os.environ.get("LSG_STEMS", "auto"),
        )
        self.session = PlaybackSession(self, create_player(audio_backend), fps)
        self._analysis_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
        self._active_file = self.data_dir / "active_project.txt"
        self._settings_file = self.data_dir / "settings.json"
        self.loop: asyncio.AbstractEventLoop | None = None
        self.ai = AgentManager(self.data_dir, f"http://{config.HOST}:{config.PORT}/mcp", self.session.broadcast_event)
        self.load_settings()

    # PC-level settings (speakers, master brightness) survive restarts
    def load_settings(self) -> None:
        try:
            data = json.loads(self._settings_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data.get("shader_isolation"), bool):
            from lsg.render import shader_host

            self.settings["shader_isolation"] = shader_host.ENABLED = data["shader_isolation"]
        if isinstance(data.get("flash_limit"), (int, float)) and 0 <= data["flash_limit"] <= 10:
            from lsg.render import safety

            self.settings["flash_limit"] = safety.LIMIT_HZ = float(data["flash_limit"])
        if isinstance(data.get("safety_ack"), bool):
            self.settings["safety_ack"] = data["safety_ack"]
        if data.get("ai_model") in AI_MODELS:
            self.settings["ai_model"] = data["ai_model"]
        if data.get("beat_tracker") in ("librosa", "beat_this", "auto"):
            self.settings["beat_tracker"] = data["beat_tracker"]
        out = self.session.output
        for key in ("brightness", "audio_latency_ms"):
            if isinstance(data.get(key), (int, float)):
                setattr(out, key, float(data[key]))

    def save_settings(self) -> None:
        atomic_write_text(self._settings_file, json.dumps({**self.session.output.to_dict(), **self.settings}, indent=2))

    def show_store(self, slug: str) -> ShowStore:
        if slug not in self.projects.list():
            raise KeyError(slug)
        return ShowStore(self.projects.project_dir(slug))

    # active project (what the UI has open; default target of MCP tools)
    @property
    def active_project(self) -> str | None:
        if self.session.loaded:
            return self.session.loaded.project_slug
        if self._active_file.is_file():
            slug = self._active_file.read_text(encoding="utf-8").strip()
            if slug in self.projects.list():
                return slug
        projects = self.projects.list()
        return projects[0] if projects else None

    async def activate_project(self, slug: str) -> None:
        if slug not in self.projects.list():
            raise KeyError(slug)
        atomic_write_text(self._active_file, slug)
        if not self.session.loaded or self.session.loaded.project_slug != slug:
            await self.session.load_project(slug)

    def resolve_project(self, slug: str | None) -> str:
        slug = slug or self.active_project
        if not slug:
            raise KeyError("no project exists yet - create one in the app first")
        if slug not in self.projects.list():
            raise KeyError(f"unknown project {slug!r}; available: {self.projects.list()}")
        return slug

    # change notifications (UI reloads, session hot-reloads)
    async def project_changed(self, slug: str) -> None:
        await self.session.reload(slug)
        await self.session.broadcast_event({"kind": "project_changed", "project": slug})

    async def show_changed(self, slug: str, show_id: str) -> None:
        await self.session.reload(slug, show_id)
        await self.session.broadcast_event({"kind": "show_changed", "project": slug, "show": show_id})

    async def shaders_changed(self, slug: str) -> None:
        await self.session.reload(slug)
        await self.session.broadcast_event({"kind": "shaders_changed", "project": slug})

    # song analysis in the background
    def analyse_song(self, song_id: str, keep_tempo: bool = True, then=None) -> None:
        """Analyse in the background; `then(song)` (a coroutine function) runs on the event loop afterwards."""
        loop = self.loop

        def progress(song) -> None:
            if loop and loop.is_running():
                event = {"kind": "song_changed", "song": song_id, "status": "running"}
                event |= {"stage": song.stage, "progress": song.progress}
                asyncio.run_coroutine_threadsafe(self.session.broadcast_event(event), loop)

        def job():
            song = self.songs.analyse(song_id, keep_tempo, progress)
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.session.broadcast_event({"kind": "song_changed", "song": song_id, "status": song.status}), loop
                )
                # shows of this song may now get beat information
                lo = self.session.loaded
                if lo and lo.show and lo.show.song_id == song_id:
                    asyncio.run_coroutine_threadsafe(self.session.reload(lo.project_slug, lo.show.id), loop)
                if then is not None:
                    asyncio.run_coroutine_threadsafe(then(song), loop)

        self._analysis_pool.submit(job)

    def resume_pending_analyses(self) -> None:
        for song in self.songs.list():
            if song.status in ("pending", "running"):
                self.analyse_song(song.id)

    def shutdown(self) -> None:
        self._analysis_pool.shutdown(wait=False, cancel_futures=True)
