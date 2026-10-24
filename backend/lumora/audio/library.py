"""Global song library: <data>/songs/<id>/{song.json, audio.<ext>, analysis.json}."""

from __future__ import annotations

import contextlib
import re
import shutil
import threading
import time
from pathlib import Path
from typing import BinaryIO

import numpy as np
import soundfile as sf

from lumora.audio.analysis import analyse_file
from lumora.model.song import Analysis, Song
from lumora.storage.project_store import atomic_write_text

AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".oga", ".aiff", ".aif"}


def _title_from_filename(name: str) -> tuple[str, str]:
    stem = re.sub(r"[_]+", " ", Path(name).stem).strip()
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return title.strip(), artist.strip()
    return stem or "Untitled", ""


def _read(path: Path) -> str:
    """Read a file the analysis may be replacing right now (Windows locks it for a moment)."""
    for attempt in range(20):
        try:
            return path.read_text(encoding="utf-8")
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.02)
    return ""


def hand_set(a: Analysis) -> bool:
    """Was the beat grid set by hand? Older analyses lack the flag: a whole-number BPM on a perfectly
    even grid (what setting the tempo produces) counts as set by hand."""
    if a.beats_edited:
        return True
    beats = np.asarray(a.beats)
    even = len(beats) > 8 and float(np.std(np.diff(beats))) < 0.002
    return float(a.bpm).is_integer() and (a.version < 2 or even)


class SongLibrary:
    def __init__(self, root: Path | str, beat_tracker=lambda: "librosa", stems=lambda: "auto"):
        self.root = Path(root)
        self.beat_tracker = beat_tracker  # callables: current settings
        self.stems = stems
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
                songs.append(self._with_date(Song.model_validate_json(_read(meta)), d))
        return sorted(songs, key=lambda s: (s.artist.lower(), s.title.lower()))

    def get(self, song_id: str) -> Song:
        meta = self._dir(song_id) / "song.json"
        if not meta.is_file():
            raise KeyError(song_id)
        return self._with_date(Song.model_validate_json(_read(meta)), meta.parent)

    @staticmethod
    def _with_date(song: Song, d: Path) -> Song:
        """Songs uploaded before the date was stored: the date of their audio file."""
        if song.added is None:
            audio = d / song.filename
            with contextlib.suppress(OSError):
                song.added = round((audio if audio.is_file() else d).stat().st_ctime, 3)
        return song

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
        song = Song(
            title=title or guessed_title,
            artist=artist if artist is not None else guessed_artist,
            filename=f"audio{ext}",
            added=round(time.time(), 3),
        )
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

    def analyse(self, song_id: str, keep_tempo: bool = True, on_progress=None) -> Song:
        """Run the analysis synchronously (call from a worker thread). keep_tempo: a tempo the user
        corrected by hand stays."""
        song = self.get(song_id)
        previous = self.analysis(song_id) if keep_tempo else None
        if previous is not None and not hand_set(previous):
            previous = None
        song.status, song.error, song.stage, song.progress = "running", None, "Warten", 0.0
        self.save(song)
        last = [0.0, ""]

        def progress(stage: str, f: float) -> None:
            if stage != last[1] or f - last[0] >= 0.05:
                last[:] = [f, stage]
                song.stage, song.progress = stage, round(f, 2)
                self.save(song)
                if on_progress:
                    on_progress(song)

        try:
            analysis = analyse_file(
                self.audio_path(song_id), self.beat_tracker(), stems=self.stems(), progress=progress, keep_tempo=previous
            )
            atomic_write_text(self._dir(song_id) / "analysis.json", analysis.model_dump_json())
            self._analysis_cache[song_id] = analysis
            song.status, song.duration = "done", analysis.duration
        except Exception as exc:  # report, never crash the worker
            song.status, song.error = "error", str(exc)
        song.stage = song.progress = None
        self.save(song)
        return song

    def scale_tempo(self, song_id: str, factor: float) -> Analysis:
        from lumora.audio.analysis import scale_tempo

        current = self.analysis(song_id)
        if current is None:
            raise ValueError("song has not been analysed yet")
        analysis = scale_tempo(current, factor)
        atomic_write_text(self._dir(song_id) / "analysis.json", analysis.model_dump_json())
        self._analysis_cache[song_id] = analysis
        return analysis

    def set_bpm(self, song_id: str, bpm: float) -> Analysis:
        from lumora.audio.analysis import set_bpm

        current = self.analysis(song_id)
        if current is None:
            raise ValueError("song has not been analysed yet")
        analysis = set_bpm(current, bpm)
        atomic_write_text(self._dir(song_id) / "analysis.json", analysis.model_dump_json())
        self._analysis_cache[song_id] = analysis
        return analysis

    def analysis(self, song_id: str) -> Analysis | None:
        if song_id in self._analysis_cache:
            return self._analysis_cache[song_id]
        path = self._dir(song_id) / "analysis.json"
        if not path.is_file():
            return None
        analysis = Analysis.model_validate_json(_read(path))
        self._analysis_cache[song_id] = analysis
        return analysis
