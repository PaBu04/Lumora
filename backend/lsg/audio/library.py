"""Global song library: <data>/songs/<id>/{song.json, audio.<ext>, analysis.json}."""

import re
import shutil
import threading
from pathlib import Path
from typing import BinaryIO

import soundfile as sf

from lsg.audio.analysis import analyse_file
from lsg.model.song import Analysis, Song
from lsg.storage.project_store import atomic_write_text

AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".oga", ".aiff", ".aif"}


def _title_from_filename(name: str) -> tuple[str, str]:
    stem = re.sub(r"[_]+", " ", Path(name).stem).strip()
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return title.strip(), artist.strip()
    return stem or "Untitled", ""


class SongLibrary:
    def __init__(self, root: Path | str, beat_tracker=lambda: "librosa"):
        self.root = Path(root)
        self.beat_tracker = beat_tracker  # callable: current setting
        self._lock = threading.Lock()
        self._analysis_cache: dict[str, Analysis] = {}

    def _dir(self, song_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", song_id):
            raise KeyError(song_id)
        return self.root / song_id

    def list(self) -> list[Song]:
        if not self.root.exists():
            return []
        songs = []
        for d in self.root.iterdir():
            meta = d / "song.json"
            if meta.is_file():
                songs.append(Song.model_validate_json(meta.read_text(encoding="utf-8")))
        return sorted(songs, key=lambda s: (s.artist.lower(), s.title.lower()))

    def get(self, song_id: str) -> Song:
        meta = self._dir(song_id) / "song.json"
        if not meta.is_file():
            raise KeyError(song_id)
        return Song.model_validate_json(meta.read_text(encoding="utf-8"))

    def save(self, song: Song) -> None:
        with self._lock:
            atomic_write_text(self._dir(song.id) / "song.json", song.model_dump_json(indent=2))

    def audio_path(self, song_id: str) -> Path:
        return self._dir(song_id) / self.get(song_id).filename

    def add(self, stream: BinaryIO, filename: str, title: str | None = None, artist: str | None = None) -> Song:
        ext = Path(filename).suffix.lower()
        if ext not in AUDIO_EXTENSIONS:
            raise ValueError(f"unsupported audio format {ext!r}")
        guessed_title, guessed_artist = _title_from_filename(filename)
        song = Song(title=title or guessed_title, artist=artist if artist is not None else guessed_artist, filename=f"audio{ext}")
        d = self._dir(song.id)
        d.mkdir(parents=True)
        try:
            with open(d / song.filename, "wb") as fh:
                shutil.copyfileobj(stream, fh)
            song.duration = round(sf.info(str(d / song.filename)).duration, 3)
        except Exception as exc:
            shutil.rmtree(d, ignore_errors=True)
            raise ValueError(f"cannot read audio file: {exc}") from exc
        self.save(song)
        return song

    def add_file(self, path: Path | str, title: str | None = None, artist: str | None = None) -> Song:
        with open(path, "rb") as fh:
            return self.add(fh, Path(path).name, title, artist)

    def update(self, song_id: str, title: str | None = None, artist: str | None = None) -> Song:
        song = self.get(song_id)
        if title is not None:
            song.title = title
        if artist is not None:
            song.artist = artist
        self.save(song)
        return song

    def delete(self, song_id: str) -> None:
        d = self._dir(song_id)
        if not d.exists():
            raise KeyError(song_id)
        self._analysis_cache.pop(song_id, None)
        shutil.rmtree(d)

    def analyse(self, song_id: str) -> Song:
        """Run the analysis synchronously (call from a worker thread)."""
        song = self.get(song_id)
        song.status, song.error = "running", None
        self.save(song)
        try:
            analysis = analyse_file(self.audio_path(song_id), self.beat_tracker())
            atomic_write_text(self._dir(song_id) / "analysis.json", analysis.model_dump_json())
            self._analysis_cache[song_id] = analysis
            song.status, song.duration = "done", analysis.duration
        except Exception as exc:  # report, never crash the worker
            song.status, song.error = "error", str(exc)
        self.save(song)
        return song

    def scale_tempo(self, song_id: str, factor: float) -> Analysis:
        from lsg.audio.analysis import scale_tempo

        current = self.analysis(song_id)
        if current is None:
            raise ValueError("song has not been analysed yet")
        analysis = scale_tempo(current, factor)
        atomic_write_text(self._dir(song_id) / "analysis.json", analysis.model_dump_json())
        self._analysis_cache[song_id] = analysis
        return analysis

    def analysis(self, song_id: str) -> Analysis | None:
        if song_id in self._analysis_cache:
            return self._analysis_cache[song_id]
        path = self._dir(song_id) / "analysis.json"
        if not path.is_file():
            return None
        analysis = Analysis.model_validate_json(path.read_text(encoding="utf-8"))
        self._analysis_cache[song_id] = analysis
        return analysis
