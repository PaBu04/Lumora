"""Fast time lookups into a song analysis for the render engine."""

from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

from lsg.audio.instruments import CURVES as INSTRUMENT_CURVES
from lsg.audio.instruments import TRACKS
from lsg.model.song import Analysis, Section

FEATURE_NAMES = ("rms", "low", "mid", "high", "onset")
CURVE_NAMES = (*FEATURE_NAMES, *INSTRUMENT_CURVES)
HIT_KINDS = ("kick", "snare", "hihat")
EVENT_KINDS = ("beat", "bar", "onset", *TRACKS)  # everything effects can be triggered by


class Events(NamedTuple):
    """Events of one track, sorted by time: arrays of equal length."""

    times: np.ndarray
    strength: np.ndarray  # 0..1
    duration: np.ndarray  # seconds, 0 = a hit
    pitch: np.ndarray  # MIDI note, 0 = none

    @staticmethod
    def of_times(times) -> "Events":
        n = len(times)
        return Events(np.asarray(times, np.float64), np.ones(n), np.zeros(n), np.zeros(n))


NO_EVENTS = Events.of_times(np.zeros(0))


@dataclass(frozen=True)
class AudioFrame:
    """Everything an effect or shader may know about the music at time t."""

    t: float
    bpm: float
    rms: float
    low: float
    mid: float
    high: float
    onset: float
    beat: float  # continuous beat count (3.5 = halfway between beat 3 and 4)
    beat_phase: float  # 0..1 within the current beat
    bar: float  # continuous bar count
    bar_phase: float  # 0..1 within the current bar
    since_beat: float  # seconds since the last beat
    since_bar: float  # seconds since the last downbeat
    since_onset: float  # seconds since the last onset
    since_kick: float  # seconds since the last kick drum hit
    since_snare: float  # seconds since the last snare / clap
    since_hihat: float  # seconds since the last hi-hat
    section: str  # intro / verse / chorus / bridge / break / outro / build / drop / ""
    section_label: str
    section_energy: float
    # instrument loudness (0..1, from the separated stems) and song shape
    drums: float = 0.0
    bass: float = 0.0
    vocals: float = 0.0
    other: float = 0.0
    density: float = 0.0  # drum hits per second relative to the busiest part
    tension: float = 0.0  # rises through a build-up, 0 after the drop
    loudness: float = 0.0  # smoothed loudness of the whole song
    brightness: float = 0.0  # how bright the keys / synths sound (0 = dull or silent)
    piano: float = 0.0  # piano / guitar loudness (6-stem separation only)
    guitar: float = 0.0


def _continuous_index(marks: np.ndarray, t: float, period: float) -> float:
    """Fractional index of t within the marker list, extrapolated with `period` outside."""
    if len(marks) == 0:
        return t / period
    if t < marks[0]:
        return (t - marks[0]) / period
    if t >= marks[-1]:
        return len(marks) - 1 + (t - marks[-1]) / period
    i = int(np.searchsorted(marks, t, side="right") - 1)
    return i + (t - marks[i]) / (marks[i + 1] - marks[i])


def _since(marks: np.ndarray, t: float) -> float:
    i = int(np.searchsorted(marks, t, side="right") - 1)
    return float(t - marks[i]) if i >= 0 else float("inf")


class AudioFeatures:
    def __init__(self, analysis: Analysis | None, duration: float | None = None):
        self.analysis = analysis
        if analysis is None:
            self.bpm = 120.0
            self.duration = duration or 0.0
            self.beats = self.downbeats = self.onsets = np.zeros(0)
            self.sections: list[Section] = []
            self.frame_rate = 1.0
            self.curves = {name: np.zeros(1) for name in CURVE_NAMES}
            self.hits = {k: np.zeros(0) for k in HIT_KINDS}
            self.tracks: dict[str, Events] = {}
            return
        self.bpm = analysis.bpm
        self.duration = analysis.duration
        self.beats = np.asarray(analysis.beats, dtype=np.float64)
        self.downbeats = np.asarray(analysis.downbeats, dtype=np.float64)
        self.onsets = np.asarray(analysis.onsets, dtype=np.float64)
        self.sections = analysis.sections
        self.frame_rate = analysis.frame_rate
        self.curves = {name: np.asarray(analysis.features[name], dtype=np.float32) for name in FEATURE_NAMES}
        if analysis.drums:
            self.hits = {k: np.asarray(analysis.drums.get(k, []), dtype=np.float64) for k in HIT_KINDS}
        else:  # analysed before drum detection existed: approximate from the band curves
            from lsg.audio.drums import from_curves

            self.hits = from_curves(self.curves, self.frame_rate)
        self.tracks = {}
        for name, evs in analysis.tracks.items():
            a = np.asarray(evs, dtype=np.float64).reshape(-1, 4)
            a = a[np.argsort(a[:, 0], kind="stable")]
            self.tracks[name] = Events(a[:, 0], a[:, 1], a[:, 2], a[:, 3])
        for k in HIT_KINDS:  # older analyses: drum hits without velocity
            if k not in self.tracks:
                self.tracks[k] = Events.of_times(self.hits[k])
        self._fill_curves(analysis)

    def _fill_curves(self, analysis: Analysis) -> None:
        """Instrument curves; analyses without separated instruments get stand-ins."""
        n = len(self.curves["rms"])
        for name in INSTRUMENT_CURVES:
            if name in analysis.features:
                self.curves[name] = np.asarray(analysis.features[name], dtype=np.float32)
        if "loudness" not in self.curves:
            w = max(1, round(0.75 * self.frame_rate))
            k = np.hanning(2 * w + 1)
            sm = np.convolve(np.pad(self.curves["rms"], w, mode="edge"), k / k.sum(), mode="valid")
            self.curves["loudness"] = np.clip(sm / (np.percentile(sm, 95) + 1e-9), 0, 1).astype(np.float32)
        if "density" not in self.curves:
            x = np.zeros(n, np.float32)
            for kind, weight in (("kick", 1.0), ("snare", 1.0), ("hihat", 0.5)):
                i = np.round(self.hits[kind] * self.frame_rate).astype(int)
                np.add.at(x, i[(i >= 0) & (i < n)], weight)
            r = max(1, round(self.frame_rate))
            x = np.convolve(x, np.ones(2 * r + 1) / (2 * r + 1), mode="same")
            self.curves["density"] = np.clip(x / (np.percentile(x, 97) + 1e-9), 0, 1).astype(np.float32)
        for name in INSTRUMENT_CURVES:
            self.curves.setdefault(name, np.zeros(1, np.float32))

    @property
    def has_instruments(self) -> bool:
        return bool(self.analysis and self.analysis.tracks)

    def events(self, kind: str, t: float, window: float) -> Events:
        """Events of `kind` (beat / bar / onset or an instrument track) within [t - window, t]."""
        ev = self.tracks.get(kind)
        if ev is None:
            if kind in ("beat", "bar", "onset"):
                return Events.of_times(self.recent(kind, t, window))
            return NO_EVENTS
        lo, hi = np.searchsorted(ev.times, [t - window, t], side="right")
        return Events(ev.times[lo:hi], ev.strength[lo:hi], ev.duration[lo:hi], ev.pitch[lo:hi])

    def pitch_range(self, kind: str) -> tuple[float, float]:
        """Typical lowest / highest note of a track (MIDI), for mapping pitch to position."""
        cache = self.__dict__.setdefault("_pitch_ranges", {})
        if kind not in cache:
            cache[kind] = self._pitch_range(kind)
        return cache[kind]

    def _pitch_range(self, kind: str) -> tuple[float, float]:
        ev = self.tracks.get(kind)
        p = ev.pitch[ev.pitch > 0] if ev is not None else np.zeros(0)
        if len(p) < 2:
            return (36.0, 84.0)
        lo, hi = np.percentile(p, [5, 95])
        return (float(lo), float(max(hi, lo + 5)))

    @property
    def beat_period(self) -> float:
        return 60.0 / self.bpm if self.bpm > 0 else 0.5

    def level(self, name: str, t: float) -> float:
        curve = self.curves[name]
        x = t * self.frame_rate
        if x <= 0:
            return float(curve[0])
        if x >= len(curve) - 1:
            return float(curve[-1])
        i = int(x)
        f = x - i
        return float(curve[i] * (1 - f) + curve[i + 1] * f)

    def beat_position(self, t: float) -> float:
        return _continuous_index(self.beats, t, self.beat_period)

    def time_at_beat(self, b: float) -> float:
        """Inverse of beat_position: song time of a (fractional) beat position."""
        marks, period = self.beats, self.beat_period
        if len(marks) < 2:
            return b * period
        if b <= 0:
            return float(marks[0] + b * period)
        if b >= len(marks) - 1:
            return float(marks[-1] + (b - (len(marks) - 1)) * period)
        i = int(b)
        return float(marks[i] + (b - i) * (marks[i + 1] - marks[i]))

    def bar_position(self, t: float) -> float:
        return _continuous_index(self.downbeats, t, 4 * self.beat_period)

    def recent(self, kind: str, t: float, window: float) -> np.ndarray:
        """Trigger times of `kind` (beat / bar / onset / kick / snare / hihat) within [t - window, t]."""
        if kind in ("beat", "bar", "onset", *HIT_KINDS):
            marks = {"beat": self.beats, "bar": self.downbeats, "onset": self.onsets, **self.hits}[kind]
        else:
            marks = self.tracks[kind].times if kind in self.tracks else np.zeros(0)
        if len(marks) == 0 and kind in ("beat", "bar"):
            # no analysis: fall back to a regular grid
            period = self.beat_period * (4 if kind == "bar" else 1)
            last = np.floor(t / period) * period
            marks = last - np.arange(int(window / period) + 1) * period
            return marks[marks >= 0][::-1]
        lo, hi = np.searchsorted(marks, [t - window, t], side="right")
        return marks[lo:hi]

    def section_at(self, t: float) -> Section | None:
        for s in self.sections:
            if s.start <= t < s.end:
                return s
        return None

    def frame(self, t: float) -> AudioFrame:
        beat = self.beat_position(t)
        bar = self.bar_position(t)
        sec = self.section_at(t)
        bp = self.beat_period
        return AudioFrame(
            t=t,
            bpm=self.bpm,
            rms=self.level("rms", t),
            low=self.level("low", t),
            mid=self.level("mid", t),
            high=self.level("high", t),
            onset=self.level("onset", t),
            beat=beat,
            beat_phase=beat % 1.0,
            bar=bar,
            bar_phase=bar % 1.0,
            since_beat=_since(self.beats, t) if len(self.beats) else (t % bp),
            since_bar=_since(self.downbeats, t) if len(self.downbeats) else (t % (4 * bp)),
            since_onset=_since(self.onsets, t),
            since_kick=_since(self.hits["kick"], t),
            since_snare=_since(self.hits["snare"], t),
            since_hihat=_since(self.hits["hihat"], t),
            section=sec.name if sec else "",
            section_label=sec.label if sec else "",
            section_energy=sec.energy if sec else 0.0,
            **{name: self.level(name, t) for name in INSTRUMENT_CURVES},
        )
