"""Diagnostics package for bug reports - without private data.

Contains versions, operating system, settings, counts (projects, strips, LEDs, controllers with
firmware and frame rate), the state of song analyses and the last log lines. Left out on purpose:
names of projects, strips, songs and controllers, IP / MAC addresses, host names, user paths and
e-mail addresses; log lines are redacted the same way.
"""

import collections
import contextlib
import json
import logging
import platform
import re
import sys
import time
from importlib import metadata

LOG_LINES = 500


class RingHandler(logging.Handler):
    """Keeps the last log records in memory for the diagnostics package."""

    def __init__(self, size: int = LOG_LINES):
        super().__init__(level=logging.INFO)
        self.lines: collections.deque[str] = collections.deque(maxlen=size)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        with contextlib.suppress(Exception):  # never break logging
            self.lines.append(self.format(record))


_ring: RingHandler | None = None


def install() -> RingHandler:
    global _ring
    if _ring is None:
        _ring = RingHandler()
        logging.getLogger().addHandler(_ring)
        if logging.getLogger().level > logging.INFO or logging.getLogger().level == logging.NOTSET:
            logging.getLogger().setLevel(logging.INFO)
    return _ring


_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<e-mail>"),
    (re.compile(r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b"), "<mac>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<ip>"),
    (re.compile(r"\b[0-9a-fA-F]{12}\b(?=[^/\\]|$)"), "<id>"),
    (re.compile(r"(?i)([a-z]:)?[\\/](users|home)[\\/][^\\/\s\"']+"), r"\1/\2/<user>"),
    (re.compile(r"(?i)\b[\w-]+\.(local|lan|fritz\.box|home)\b"), "<host>"),
]


def redact(text: str, names: list[str] | None = None) -> str:
    """Remove addresses, user paths and host names - and every name in `names` (projects, strips,
    controllers, songs: whatever the user typed)."""
    for name in sorted(names or [], key=len, reverse=True):
        if len(name) >= 3:
            text = re.sub(re.escape(name), "<name>", text, flags=re.IGNORECASE)
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


def private_names(st) -> list[str]:
    """Everything the user named: it never goes into the package."""
    out: list[str] = []
    for slug in st.projects.list():
        out.append(slug)
        try:
            p = st.projects.load(slug)
        except Exception:
            continue
        out += [p.name, *(f.name for f in p.fixtures), *(c.name for c in p.controllers), *(c.host for c in p.controllers)]
        out += [s.name for s in st.show_store(slug).list()]
    for s in st.songs.list():
        out += [s.title, s.artist, s.filename]
    return [n for n in out if n]


def _version(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def _controller(status: dict | None) -> dict | None:
    """The harmless part of a WLED status: no name, address or Wi-Fi network."""
    if not status:
        return None
    info = status.get("info") or {}
    leds = info.get("leds") or {}
    wifi = info.get("wifi") or {}
    return {
        "ok": status.get("ok"),
        "error": redact(str(status["error"])) if status.get("error") else None,
        "firmware": info.get("ver"),
        "chip": info.get("arch"),
        "leds": leds.get("count"),
        "wled_fps": leds.get("fps"),
        "sent_fps": status.get("sent_fps"),
        "wifi_signal": wifi.get("signal"),
        "warnings": [redact(str(w)) for w in status.get("warnings", [])][:10],
    }


def collect(st) -> dict:
    """Everything in the package, already without private data."""
    projects = []
    for slug in st.projects.list():
        try:
            p = st.projects.load(slug)
        except Exception as exc:
            projects.append({"error": redact(str(exc))[:300]})
            continue
        led_types = collections.Counter(str(f.led_type) for f in p.fixtures)
        shows = st.show_store(slug).list()
        status = st.session.controller_status if st.session.loaded and st.session.loaded.project_slug == slug else {}
        projects.append(
            {
                "active": slug == st.active_project,
                "strips": len(p.fixtures),
                "led_types": dict(led_types),
                "shapes": dict(collections.Counter(f.geometry.type for f in p.fixtures)),
                "controllers": [
                    {
                        "rgbw": c.rgbw,
                        "mapped_strips": len(c.mappings),
                        "max_fps": c.max_fps,
                        "latency_ms": c.latency_ms,
                        "budget_ma": c.budget_ma,
                        "status": _controller(status.get(c.id)),
                    }
                    for c in p.controllers
                ],
                "shows": len(shows),
                "clips": sum(len(layer.clips) for s in shows for layer in s.layers),
                "calibration": {k: v.model_dump() for k, v in p.calibration.items()},
            }
        )
    songs = []
    for s in st.songs.list():
        a = st.songs.analysis(s.id) if s.status == "done" else None
        songs.append(
            {
                "status": s.status,
                "error": redact(s.error)[:300] if s.error else None,
                "duration": round(s.duration or 0, 1),
                "format": s.filename.rsplit(".", 1)[-1].lower() if s.filename else None,
                "analysis": {
                    "version": a.version,
                    "stems": a.stems,
                    "beat_source": a.beat_source,
                    "bpm": a.bpm,
                    "beats_edited": a.beats_edited,
                    "sections": len(a.sections),
                    "tracks": {k: len(v) for k, v in a.tracks.items()},
                    "key": (a.harmony or {}).get("key"),
                    "motifs": len(a.motifs),
                }
                if a
                else None,
            }
        )
    pb = st.session.state()
    return {
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "app": _version("lsg") or "dev",
        "python": sys.version.split()[0],
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "packages": {
            p: _version(p)
            for p in ("numpy", "librosa", "fastapi", "uvicorn", "mcp", "onnxruntime", "torch", "torchaudio", "beat_this")
        },
        "settings": {k: v for k, v in st.settings.items() if k != "remote_key"},  # the remote's key is a secret
        "output": st.session.output.to_dict(),
        "playback": {
            "mode": pb.get("mode"),
            "fps": pb.get("fps"),
            "render_ms": pb.get("render_ms"),
            "led_count": pb.get("led_count"),
            "clip_errors": len(pb.get("clip_errors") or {}),
            "controller_errors": [redact(str(e))[:200] for e in (pb.get("controller_errors") or {}).values()],
        },
        "projects": projects,
        "songs": songs,
    }


def log_text(st=None) -> str:
    lines = list(_ring.lines) if _ring else []
    return redact("\n".join(lines), private_names(st) if st is not None else None) or "(keine Log-Einträge)"


def package(st) -> bytes:
    """diagnostics.json + log.txt as a zip."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        names = private_names(st)
        z.writestr("diagnostics.json", redact(json.dumps(collect(st), indent=2, ensure_ascii=False, default=str), names))
        z.writestr("log.txt", log_text(st))
        z.writestr(
            "LIESMICH.txt",
            "Diagnosepaket des Light Show Generators. Es enthält Versionen, Einstellungen, Anzahlen und die letzten\n"
            "Log-Zeilen - ohne Namen von Projekten, Strips, Songs und Controllern, ohne IP-/MAC-Adressen, Rechnernamen,\n"
            "Benutzerpfade und E-Mail-Adressen. Du kannst beide Dateien vor dem Weitergeben ansehen.\n",
        )
    return buf.getvalue()
