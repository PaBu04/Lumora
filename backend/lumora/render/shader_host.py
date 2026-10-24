"""Runs shaders in a separate worker process.

A shader that hangs is killed after FRAME_TIMEOUT (the clip is disabled with an error, the
app keeps running), and a crash inside a shader cannot take the app down. The static code
check of lumora.render.shaders still applies on top. LED tables and LED selections are sent
to the worker once and cached there; per frame only time, audio values and params travel.
"""

import contextlib
import hashlib
import logging
import multiprocessing as mp
import threading
import uuid
from dataclasses import asdict

import numpy as np

from lumora.render.shaders import Shader, ShaderError

log = logging.getLogger(__name__)

ENABLED = True  # run shaders in the worker process (setting "shader_isolation")
FRAME_TIMEOUT = 0.5  # seconds per shader call before the worker is killed
START_TIMEOUT = 30.0  # first start imports numpy etc.
TABLE_FIELDS = (
    "pos",
    "norm_pos",
    "fixture_index",
    "index_in_fixture",
    "u",
    "azimuth",
    "elevation",
    "distance",
    "s",
    "view",
    "fixture_offsets",
)


# ---------------------------------------------------------------- worker side


def _worker(conn) -> None:  # pragma: no cover - runs in the child process (covered by tests through the host)
    from lumora.audio.features import AudioFrame
    from lumora.geometry.led_table import LedTable
    from lumora.render.context import LedView, RenderContext, Spatial

    tables: dict[str, tuple] = {}
    views: dict[str, LedView] = {}
    shaders: dict[str, Shader] = {}
    conn.send(("ready",))
    while True:
        try:
            msg = conn.recv()
        except EOFError:
            return
        kind = msg[0]
        try:
            if kind == "table":
                _, key, data, center = msg
                table = LedTable(fixture_ids=data.pop("fixture_ids"), **data)
                tables[key] = (table, Spatial(table, center))
                if len(tables) > 4:
                    tables.pop(next(iter(tables)))
                conn.send(("ok",))
            elif kind == "view":
                _, key, table_key, idx = msg
                table, spatial = tables[table_key]
                views[key] = LedView(table, spatial, idx)
                if len(views) > 512:
                    views.pop(next(iter(views)))
                conn.send(("ok",))
            elif kind == "shader":
                _, key, name, source = msg
                shaders[key] = Shader(name, source)
                conn.send(("ok",))
            elif kind == "render":
                _, shader_key, view_key, t, lt, duration, audio, params, seed, viewer = msg
                ctx = RenderContext(
                    t=t,
                    lt=lt,
                    duration=duration,
                    leds=views[view_key],
                    audio=AudioFrame(**audio),
                    features=None,
                    seed=seed,
                    viewer_pos=np.asarray(viewer, np.float32),
                )
                rgb, alpha = shaders[shader_key](ctx, params)
                conn.send(
                    (
                        "result",
                        np.ascontiguousarray(rgb, np.float32),
                        None if alpha is None else np.ascontiguousarray(alpha, np.float32),
                    )
                )
            elif kind == "stop":
                return
        except KeyError as exc:
            conn.send(("missing", str(exc)))
        except Exception as exc:
            conn.send(("error", f"{type(exc).__name__}: {exc}"))


# ---------------------------------------------------------------- host side


class ShaderHost:
    """One worker process shared by all renderers (calls are serialised)."""

    def __init__(self):
        self._lock = threading.RLock()
        self._proc = None
        self._conn = None
        self._sent: set[str] = set()

    def _start(self) -> None:
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        self._proc = ctx.Process(target=_worker, args=(child,), daemon=True, name="lumora-shaders")
        self._proc.start()
        child.close()
        self._conn = parent
        self._sent = set()
        if not parent.poll(START_TIMEOUT):
            self.restart()
            raise ShaderError("shader worker did not start")
        parent.recv()

    def restart(self) -> None:
        if self._proc is not None:
            self._proc.kill()
            self._proc.join(2)
        self._proc = self._conn = None
        self._sent = set()

    def _call(self, msg, timeout: float):
        if self._proc is None or not self._proc.is_alive():
            self._start()
        self._conn.send(msg)
        if not self._conn.poll(timeout):
            self.restart()
            raise ShaderError(f"shader took longer than {timeout * 1000:.0f} ms - stopped (endless loop or too heavy?)")
        try:
            reply = self._conn.recv()
        except EOFError:
            self.restart()
            raise ShaderError("shader worker crashed") from None
        if reply[0] == "error":
            raise ShaderError(reply[1])
        return reply

    def _ensure(self, key: str, msg) -> None:
        if key not in self._sent:
            self._call(msg, START_TIMEOUT)
            self._sent.add(key)

    def render(self, shader: "IsolatedShader", ctx, params: dict):
        table = ctx.leds.table
        table_key = _tag(table, "_lumora_key")
        view = ctx.leds
        view_key = getattr(view, "_lumora_key", None)
        if view_key is None:
            view_key = f"{table_key}:{hashlib.sha1(view.idx.tobytes()).hexdigest()}"
            view._lumora_key = view_key
        with self._lock:
            for attempt in range(2):
                self._ensure(table_key, ("table", table_key, _table_payload(table), tuple(ctx.leds.spatial.center.tolist())))
                self._ensure(view_key, ("view", view_key, table_key, view.idx))
                self._ensure(shader.key, ("shader", shader.key, shader.name, shader.source))
                reply = self._call(
                    (
                        "render",
                        shader.key,
                        view_key,
                        float(ctx.t),
                        float(ctx.lt),
                        float(ctx.duration),
                        asdict(ctx.audio),
                        params,
                        int(ctx.seed),
                        np.asarray(ctx.viewer_pos).tolist(),
                    ),
                    FRAME_TIMEOUT,
                )
                if reply[0] == "missing" and attempt == 0:  # worker restarted meanwhile: resend caches
                    self._sent.clear()
                    continue
                if reply[0] != "result":
                    raise ShaderError(f"unexpected shader worker reply {reply[0]}")
                return reply[1], reply[2]
        raise ShaderError("shader worker lost its state")

    def close(self) -> None:
        with self._lock:
            if self._conn is not None and self._proc is not None and self._proc.is_alive():
                with contextlib.suppress(OSError):
                    self._conn.send(("stop",))
                self._proc.join(2)
            self.restart()


def _tag(obj, attr: str) -> str:
    key = getattr(obj, attr, None)
    if key is None:
        key = uuid.uuid4().hex
        object.__setattr__(obj, attr, key)  # LedTable is a frozen dataclass
    return key


def _table_payload(table) -> dict:
    return {"fixture_ids": list(table.fixture_ids), **{f: getattr(table, f) for f in TABLE_FIELDS}}


_host: ShaderHost | None = None
_host_lock = threading.Lock()


def host() -> ShaderHost:
    global _host
    with _host_lock:
        if _host is None:
            _host = ShaderHost()
        return _host


def shutdown() -> None:
    global _host
    with _host_lock:
        if _host is not None:
            _host.close()
            _host = None


class IsolatedShader:
    """Same interface as Shader, but executed in the worker process."""

    def __init__(self, shader: Shader):
        self.name = shader.name
        self.source = shader.source
        self.key = f"{shader.name}:{hashlib.sha1(shader.source.encode()).hexdigest()[:12]}"

    def __call__(self, ctx, params: dict):
        return host().render(self, ctx, params)
