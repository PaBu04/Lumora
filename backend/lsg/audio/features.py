"""Fast time lookups into a song analysis for the render engine."""

from dataclasses import dataclass

import numpy as np

from lsg.model.song import Analysis, Section

FEATURE_NAMES = ("rms", "low", "mid", "high", "onset")


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
    section: str  # intro / verse / chorus / bridge / break / outro / ""
    section_label: str
    section_energy: float


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
            self.curves = {name: np.zeros(1) for name in FEATURE_NAMES}
            return
        self.bpm = analysis.bpm
        self.duration = analysis.duration
        self.beats = np.asarray(analysis.beats, dtype=np.float64)
        self.downbeats = np.asarray(analysis.downbeats, dtype=np.float64)
        self.onsets = np.asarray(analysis.onsets, dtype=np.float64)
        self.sections = analysis.sections
        self.frame_rate = analysis.frame_rate
        self.curves = {name: np.asarray(analysis.features[name], dtype=np.float32) for name in FEATURE_NAMES}

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

    def bar_position(self, t: float) -> float:
        return _continuous_index(self.downbeats, t, 4 * self.beat_period)

    def recent(self, kind: str, t: float, window: float) -> np.ndarray:
        """Trigger times of `kind` (beat / bar / onset) within [t - window, t]."""
        marks = {"beat": self.beats, "bar": self.downbeats, "onset": self.onsets}[kind]
        if len(marks) == 0 and kind != "onset":
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
            section=sec.name if sec else "",
            section_label=sec.label if sec else "",
            section_energy=sec.energy if sec else 0.0,
        )
