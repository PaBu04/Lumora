from typing import Literal

from pydantic import BaseModel, Field

from lsg.model.common import Id, new_id

AnalysisStatus = Literal["pending", "running", "done", "error"]


class Song(BaseModel):
    id: Id = Field(default_factory=new_id)
    title: str
    artist: str = ""
    filename: str
    duration: float = 0.0
    status: AnalysisStatus = "pending"
    error: str | None = None
    stage: str | None = None  # what the running analysis is doing
    progress: float | None = None  # 0..1 while running


class Section(BaseModel):
    start: float
    end: float
    name: str  # intro / verse / prechorus / chorus / bridge / break / build / drop / outro
    label: str  # A, B, C ... sections with the same label sound alike
    energy: float  # mean loudness 0..1
    bars: int = 0  # length in bars (0 = unknown)
    repeat: int = 1  # 2 = the second time this label comes
    intensity: int = 3  # 1 (quietest part of the song) .. 5 (most intense)
    peak: bool = False  # the song's climax: keep the brightest moment of a show for it


class Analysis(BaseModel):
    """Result of the audio analysis. Feature curves are sampled at `frame_rate` Hz, normalised 0..1."""

    version: int = 1  # 2 = with instrument tracks
    duration: float
    bpm: float
    beats: list[float]
    downbeats: list[float]
    onsets: list[float]
    sections: list[Section]
    frame_rate: float
    features: dict[str, list[float]]  # rms, low, mid, high, onset
    waveform: list[float]  # peak envelope for drawing, ~WAVEFORM_POINTS values
    beat_source: str = "librosa"  # librosa | beat_this
    beat_note: str | None = None  # why the preferred tracker was not used
    drums: dict[str, list[float]] = Field(default_factory=dict)  # kick / snare / hihat hit times
    beats_per_bar: int = 4
    beats_edited: bool = False  # tempo set by hand: kept when the song is analysed again
    stems: str | None = None  # how instruments were separated: "demucs", "approx" (no vocals) or None
    # instrument tracks (see lsg.audio.instruments): name -> events [time, strength, duration, pitch]
    tracks: dict[str, list[list[float]]] = Field(default_factory=dict)
    # key and chords (lsg.audio.harmony): {"key": "F♯ Moll", "tonic": 6, "mode": "minor", "confidence",
    # "chords": [[start, duration, name, degree, strength]]}
    harmony: dict | None = None
    # phrases of the song form (lsg.audio.structure): [start s, bars], 4 or 8 bars each
    phrases: list[list[float]] = Field(default_factory=list)
