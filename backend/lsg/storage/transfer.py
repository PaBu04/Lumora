"""Projects as a single file: export to a zip and import it again (backup, another PC, sharing).

Layout of the zip:
  manifest.json                        {"format": "lsg-project", "version": 1, ...}
  project.json, looks.json, floorplan.<ext>
  shows/<id>.json, shows/order.json, shaders/<name>.py
  songs/<id>/song.json, analysis.json, audio.<ext>   (only with songs)

Importing accepts only these paths, checks every JSON file against the models and creates a new
project (the original stays untouched). Songs keep their ids, so the shows still find them; a song
that is already in the library is not copied again.
"""

import json
import re
import time
import zipfile
from pathlib import Path

from lsg.audio.library import SongLibrary
from lsg.model.project import Project
from lsg.model.show import Show
from lsg.model.song import Analysis, Song
from lsg.storage.project_store import ProjectStore, atomic_write_text

FORMAT = "lsg-project"
VERSION = 1
MAX_BYTES = 4 * 1024**3  # uncompressed: songs can be large, but not endless
_ID = r"[A-Za-z0-9_-]{1,64}"
ALLOWED = [
    re.compile(r"manifest\.json"),
    re.compile(r"project\.json"),
    re.compile(r"looks\.json"),
    re.compile(r"floorplan\.(png|jpe?g|webp|gif|bmp)"),
    re.compile(rf"shows/{_ID}\.json"),
    re.compile(r"shaders/[a-z][a-z0-9_]{0,40}\.py"),
    re.compile(rf"songs/{_ID}/(song\.json|analysis\.json|audio\.[a-z0-9]{{2,5}})"),
]


class ImportError_(ValueError):
    """The file is not a project export (or a broken one)."""


def export_project(projects: ProjectStore, songs: SongLibrary, slug: str, out: Path, with_songs: bool = True) -> Path:
    src = projects.project_dir(slug)
    project = projects.load(slug)
    used: set[str] = set()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((src / "shows").glob("*.json")):
            z.write(f, f"shows/{f.name}")
            if f.name != "order.json":
                sid = json.loads(f.read_text(encoding="utf-8")).get("song_id")
                if sid:
                    used.add(sid)
        for f in sorted((src / "shaders").glob("*.py")):
            z.write(f, f"shaders/{f.name}")
        for name in ("looks.json",):
            if (src / name).is_file():
                z.write(src / name, name)
        if project.floorplan and (src / project.floorplan.filename).is_file():
            z.write(src / project.floorplan.filename, project.floorplan.filename)
        z.writestr("project.json", project.model_dump_json(indent=2))
        exported = []
        if with_songs:
            for sid in sorted(used):
                try:
                    song = songs.get(sid)
                    audio = songs.audio_path(sid)
                except KeyError:
                    continue
                d = audio.parent
                z.writestr(f"songs/{sid}/song.json", song.model_dump_json(indent=2))
                if (d / "analysis.json").is_file():
                    z.write(d / "analysis.json", f"songs/{sid}/analysis.json")
                z.write(audio, f"songs/{sid}/audio{audio.suffix.lower()}", compress_type=zipfile.ZIP_STORED)
                exported.append(sid)
        manifest = {
            "format": FORMAT,
            "version": VERSION,
            "name": project.name,
            "exported": time.strftime("%Y-%m-%d %H:%M:%S"),
            "songs": exported,
            "songs_missing": sorted(used - set(exported)) if with_songs else sorted(used),
        }
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    return out


def import_project(projects: ProjectStore, songs: SongLibrary, path: Path) -> tuple[str, dict]:
    """Create a new project from an export; returns (slug, summary)."""
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ImportError_("keine Projektdatei (kein ZIP-Archiv)") from exc
    with z:
        names = [i.filename for i in z.infolist() if not i.is_dir()]
        bad = [n for n in names if not any(p.fullmatch(n) for p in ALLOWED)]
        if bad:
            raise ImportError_(f"unerwartete Dateien im Archiv: {', '.join(bad[:5])}")
        if sum(i.file_size for i in z.infolist()) > MAX_BYTES:
            raise ImportError_("Archiv zu groß")
        if "manifest.json" not in names or "project.json" not in names:
            raise ImportError_("keine Projektdatei dieser App (manifest.json / project.json fehlt)")
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("format") != FORMAT:
            raise ImportError_("keine Projektdatei dieser App")
        if int(manifest.get("version", 0)) > VERSION:
            raise ImportError_("die Datei stammt aus einer neueren Version der App")
        try:
            project = Project.model_validate_json(z.read("project.json"))
            shows = {n: Show.model_validate_json(z.read(n)) for n in names if n.startswith("shows/") and n != "shows/order.json"}
            song_meta = {n.split("/")[1]: Song.model_validate_json(z.read(n)) for n in names if n.endswith("/song.json")}
            for n in names:
                if n.endswith("/analysis.json"):
                    Analysis.model_validate_json(z.read(n))
        except ValueError as exc:
            raise ImportError_(f"beschädigte Projektdatei: {exc}") from exc

        existing = {p.name for p in (projects.load(s) for s in projects.list())}
        name, n = project.name, 2
        while name in existing:
            name, n = f"{project.name} ({n})", n + 1
        project.name = name
        slug = projects.create(project)
        dst = projects.project_dir(slug)
        for n in names:
            if n in ("manifest.json", "project.json") or n.startswith("songs/"):
                continue
            target = dst / n
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(n))
        # shows were validated above; write them in the current format
        for n, show in shows.items():
            atomic_write_text(dst / n, show.model_dump_json(indent=2))

        added, kept = [], []
        for sid, song in song_meta.items():
            try:
                songs.get(sid)
                kept.append(sid)
                continue
            except KeyError:
                pass
            audio = next((n for n in names if n.startswith(f"songs/{sid}/audio.")), None)
            if audio is None:
                continue
            d = songs.root / sid
            d.mkdir(parents=True, exist_ok=True)
            song.filename = Path(audio).name
            (d / song.filename).write_bytes(z.read(audio))
            if f"songs/{sid}/analysis.json" in names:
                (d / "analysis.json").write_bytes(z.read(f"songs/{sid}/analysis.json"))
            elif song.status == "done":
                song.status = "pending"
            songs.save(song)
            added.append(sid)
    return slug, {"name": name, "shows": len(shows), "songs_added": added, "songs_present": kept}
