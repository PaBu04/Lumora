"""Version history for JSON documents (shows, projects).

Every save stores the new state as a version file `<ms timestamp>-<source>.json`. Rapid
saves from the UI (dragging, typing) within COALESCE_SECONDS replace the previous UI
version so the list stays readable; AI edits always create their own version, so any
AI change can be rolled back individually.
"""

import json
import re
import time
from pathlib import Path

from lsg.storage.project_store import atomic_write_text

SOURCES = ("ui", "ai", "system", "restore")
COALESCE_SECONDS = 60.0
MAX_VERSIONS = 200
_NAME = re.compile(r"^(\d{13})-(ui|ai|system|restore)$")


class History:
    def __init__(self, directory: Path):
        self.dir = directory

    def _entries(self) -> list[tuple[int, str, Path]]:
        if not self.dir.exists():
            return []
        out = []
        for p in self.dir.glob("*.json"):
            m = _NAME.match(p.stem)
            if m:
                out.append((int(m.group(1)), m.group(2), p))
        return sorted(out)

    def record(self, content: str, source: str, summary: str) -> str:
        if source not in SOURCES:
            source = "ui"
        entries = self._entries()
        now = int(time.time() * 1000)
        if entries:
            ts, src, path = entries[-1]
            if json.loads(path.read_text(encoding="utf-8"))["content"] == content:
                return path.stem  # nothing changed
            if src == "ui" and source == "ui" and (now - ts) / 1000 < COALESCE_SECONDS:
                previous = json.loads(path.read_text(encoding="utf-8"))
                summary = _merge_summary(previous.get("summary", ""), summary)
                path.unlink()
        now = max(now, entries[-1][0] + 1 if entries else now)
        vid = f"{now}-{source}"
        atomic_write_text(self.dir / f"{vid}.json", json.dumps({"summary": summary, "content": content}))
        for _, _, p in self._entries()[:-MAX_VERSIONS]:
            p.unlink(missing_ok=True)
        return vid

    def first_time(self) -> float | None:
        """Unix time of the oldest version."""
        entries = self._entries()
        return entries[0][0] / 1000 if entries else None

    def list(self) -> list[dict]:
        out = []
        for ts, src, p in reversed(self._entries()):
            try:
                summary = json.loads(p.read_text(encoding="utf-8")).get("summary", "")
            except (OSError, ValueError):
                summary = "?"
            out.append({"id": p.stem, "time": ts / 1000, "source": src, "summary": summary})
        return out

    def get(self, version_id: str) -> str:
        if not _NAME.match(version_id):
            raise KeyError(version_id)
        path = self.dir / f"{version_id}.json"
        if not path.is_file():
            raise KeyError(version_id)
        return json.loads(path.read_text(encoding="utf-8"))["content"]

    def latest_content(self) -> str | None:
        entries = self._entries()
        if not entries:
            return None
        return json.loads(entries[-1][2].read_text(encoding="utf-8"))["content"]


def _merge_summary(a: str, b: str) -> str:
    parts = [p for p in (a.split("; ") + b.split("; ")) if p]
    seen = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    return "; ".join(seen[-4:])


def show_summary(old: dict | None, new: dict) -> str:
    """Human readable difference between two show JSON dicts."""
    if old is None:
        return f"erstellt ({sum(len(l['clips']) for l in new['layers'])} Clips)"
    old_clips = {c["id"]: c for l in old["layers"] for c in l["clips"]}
    new_clips = {c["id"]: c for l in new["layers"] for c in l["clips"]}
    added = len(new_clips.keys() - old_clips.keys())
    removed = len(old_clips.keys() - new_clips.keys())
    changed = sum(1 for k in new_clips.keys() & old_clips.keys() if new_clips[k] != old_clips[k])
    parts = []
    if added:
        parts.append(f"+{added} Clip{'s' if added > 1 else ''}")
    if removed:
        parts.append(f"−{removed} Clip{'s' if removed > 1 else ''}")
    if changed:
        parts.append(f"{changed} Clip{'s' if changed > 1 else ''} geändert")
    if [l["name"] for l in old["layers"]] != [l["name"] for l in new["layers"]]:
        parts.append("Ebenen geändert")
    for key, label in (("name", "Name"), ("song_id", "Song"), ("master", "Master")):
        if old.get(key) != new.get(key):
            parts.append(f"{label} geändert")
    return ", ".join(parts) or "geändert"


def project_summary(old: dict | None, new: dict) -> str:
    if old is None:
        return "erstellt"
    parts = []
    if old["room"] != new["room"]:
        parts.append("Raum")
    if old["viewer"] != new["viewer"]:
        parts.append("Betrachter")
    of, nf = {f["id"]: f for f in old["fixtures"]}, {f["id"]: f for f in new["fixtures"]}
    if nf.keys() - of.keys():
        parts.append(f"+{len(nf.keys() - of.keys())} Strip(s)")
    if of.keys() - nf.keys():
        parts.append(f"−{len(of.keys() - nf.keys())} Strip(s)")
    if any(nf[k] != of[k] for k in nf.keys() & of.keys()):
        parts.append("Strips geändert")
    if old["controllers"] != new["controllers"]:
        parts.append("Controller")
    if old.get("calibration") != new.get("calibration"):
        parts.append("Kalibrierung")
    if old.get("power") != new.get("power"):
        parts.append("Strombudget")
    if old["name"] != new["name"]:
        parts.append("Name")
    return ", ".join(parts) or "geändert"
