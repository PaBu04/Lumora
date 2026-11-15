"""Projects as a single file: export to a zip and import it again (backup, another PC, sharing).

Layout of the zip:
  manifest.json                        {"format": "lumora-project", "version": 1, ...}
  project.json, looks.json, floorplan.<ext>
  shows/<id>.json, shows/order.json, shaders/<name>.py
  songs/<id>/song.json, analysis.json, audio.<ext>   (only with songs)

Importing accepts only these paths, checks every JSON file against the models and creates a new
project (the original stays untouched). Songs keep their ids, so the shows still find them; a song
that is already in the library is not copied again.
"""

import json
import re
import shutil
import time
import zipfile
from pathlib import Path

from lumora.audio.library import SongLibrary
from lumora.model.project import Project
from lumora.model.show import Show
from lumora.model.song import Analysis, Song
from lumora.storage.project_store import ProjectStore, atomic_write_text

FORMAT = "lumora-project"
VERSION = 1
MAX_BYTES = 4 * 1024**3  # uncompressed: songs can be large, but not endless
MAX_JSON_BYTES = 64 * 1024**2  # one JSON document (they are read into memory)
MAX_SHADER_BYTES = 1024**2
MAX_FILES = 5000
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


class _Budget:
    """Bytes the import may still unpack. The sizes in a zip's directory are only claims, so the
    limit is enforced on what really comes out."""

    def __init__(self, limit: int):
        self.left = limit

    def take(self, n: int) -> None:
        self.left -= n
        if self.left < 0:
            raise ImportError_("Archiv zu groß")


def _read(z: zipfile.ZipFile, name: str, budget: _Budget, limit: int = MAX_JSON_BYTES) -> bytes:
    """A member that is parsed in memory (JSON, shader source)."""
    with z.open(name) as src:
        data = src.read(limit + 1)
    if len(data) > limit:
        raise ImportError_(f"{name} ist zu groß")
    budget.take(len(data))
    return data


def _extract(z: zipfile.ZipFile, name: str, target: Path, budget: _Budget) -> None:
    """Write a member to disk in pieces (audio files are large)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with z.open(name) as src, target.open("wb") as dst:
        while chunk := src.read(1024 * 1024):
            budget.take(len(chunk))
            dst.write(chunk)


def _check_documents(z: zipfile.ZipFile, names: list[str], budget: _Budget) -> tuple[dict[str, bytes], list[str]]:
    """The small files besides project, shows and songs - read and checked before anything is written.
    Returns them by name, plus the shaders that fail the code check (they are left out)."""
    from lumora.render.looks import Look
    from lumora.render.shaders import ShaderError, check_source

    documents, refused = {}, []
    for n in names:
        if n.endswith("/analysis.json"):
            documents[n] = _read(z, n, budget)
            Analysis.model_validate_json(documents[n])
        elif n == "looks.json":
            documents[n] = _read(z, n, budget)
            for look in json.loads(documents[n]):
                Look.model_validate(look)
        elif n == "shows/order.json":
            documents[n] = _read(z, n, budget)
            if not isinstance(json.loads(documents[n]), list):
                raise ImportError_("shows/order.json ist keine Liste")
        elif n.startswith("shaders/"):
            source = _read(z, n, budget, MAX_SHADER_BYTES)
            try:  # the same check as when a shader is saved in the app
                check_source(source.decode("utf-8"))
                documents[n] = source
            except (ShaderError, UnicodeDecodeError):
                refused.append(n)
    return documents, refused


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
        if len(names) > MAX_FILES or len(set(names)) != len(names) or sum(i.file_size for i in z.infolist()) > MAX_BYTES:
            raise ImportError_("Archiv zu groß")
        if "manifest.json" not in names or "project.json" not in names:
            raise ImportError_("keine Projektdatei dieser App (manifest.json / project.json fehlt)")
        budget = _Budget(MAX_BYTES)
        try:
            manifest = json.loads(_read(z, "manifest.json", budget))
            if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
                raise ImportError_("keine Projektdatei dieser App")
            if int(manifest.get("version", 0)) > VERSION:
                raise ImportError_("die Datei stammt aus einer neueren Version der App")
            project = Project.model_validate_json(_read(z, "project.json", budget))
            shows = {}
            for n in names:
                if n.startswith("shows/") and n != "shows/order.json":
                    shows[n] = Show.model_validate_json(_read(z, n, budget))
            for n, show in shows.items():  # a show is stored under its id
                if n != f"shows/{show.id}.json":
                    raise ImportError_(f"{n} enthält eine Show mit anderer id")
            song_meta = {}
            for n in names:
                if n.endswith("/song.json"):
                    song_meta[n.split("/")[1]] = Song.model_validate_json(_read(z, n, budget))
            for sid, song in song_meta.items():
                if song.id != sid:
                    raise ImportError_(f"songs/{sid}/song.json enthält einen Song mit anderer id")
            documents, refused = _check_documents(z, names, budget)
        except ImportError_:
            raise
        except (ValueError, TypeError, zipfile.BadZipFile) as exc:
            raise ImportError_(f"beschädigte Projektdatei: {exc}") from exc
        if project.floorplan and project.floorplan.filename not in names:
            project.floorplan = None  # exported without its image

        existing = {p.name for p in (projects.load(s) for s in projects.list())}
        name, n = project.name, 2
        while name in existing:
            name, n = f"{project.name} ({n})", n + 1
        project.name = name
        slug = projects.create(project)
        dst = projects.project_dir(slug)
        added, kept = [], []
        try:
            for n in names:
                if n in ("manifest.json", "project.json") or n.startswith("songs/") or n in shows or n in refused:
                    continue
                if n in documents:
                    (dst / n).parent.mkdir(parents=True, exist_ok=True)
                    (dst / n).write_bytes(documents[n])
                else:  # the floor plan image
                    _extract(z, n, dst / n, budget)
            # shows were validated above; write them in the current format
            for n, show in shows.items():
                atomic_write_text(dst / n, show.model_dump_json(indent=2))

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
                added.append(sid)
                song.filename = Path(audio).name
                _extract(z, audio, d / song.filename, budget)
                analysis = documents.get(f"songs/{sid}/analysis.json")
                if analysis is not None:
                    (d / "analysis.json").write_bytes(analysis)
                elif song.status == "done":
                    song.status = "pending"
                songs.save(song)
        except BaseException:  # leave nothing half imported behind
            shutil.rmtree(dst, ignore_errors=True)
            for sid in added:
                shutil.rmtree(songs.root / sid, ignore_errors=True)
            raise
    summary = {"name": name, "shows": len(shows), "songs_added": added, "songs_present": kept}
    return slug, {**summary, "shaders_refused": [Path(n).stem for n in refused]}
