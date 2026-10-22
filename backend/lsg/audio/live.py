"""Real-time audio analysis for the live input mode (microphone, line-in or the PC's own
sound output, no pre-analysis).

LiveAudioFeatures offers the same interface as AudioFeatures, so every effect and shader
works unchanged:
  levels   rms / low / mid / high from a sliding FFT, normalised by slowly decaying peaks
  onsets   spectral flux, adaptive threshold
  tempo    autocorrelation of the onset curve over the last ~8 s (70-180 BPM, prior at 120)
  beats    phase from a comb filter over recent onsets; the beat grid is extrapolated
Time is seconds since the live mode started.
"""

import re
import threading
import time
from collections import deque

import numpy as np

from lsg.audio.features import FEATURE_NAMES, AudioFrame
from lsg.model.song import Section

HOP_SECONDS = 1 / 86.0
WINDOW = 2048
BANDS = {"low": (20, 250), "mid": (250, 2000), "high": (2000, 11000)}
TEMPO_HISTORY = 8.0
MIN_BPM, MAX_BPM = 70.0, 180.0


class _Follower:
    """Peak follower for adaptive normalisation (attack immediate, release over `release` s)."""

    def __init__(self, release: float, floor: float):
        self.peak = floor
        self.floor = floor
        self.release = release

    def norm(self, x: float, dt: float) -> float:
        self.peak = max(x, self.floor, self.peak * float(np.exp(-dt / self.release)))
        return min(1.0, x / self.peak)


class LiveAudioFeatures:
    def __init__(self, sample_rate: int):
        self.sr = sample_rate
        self.hop = max(64, int(sample_rate * HOP_SECONDS))
        self.frame_rate = sample_rate / self.hop
        self._buf = np.zeros(WINDOW, np.float32)
        self._pending = np.zeros(0, np.float32)
        self._lock = threading.Lock()
        self._window = np.hanning(WINDOW).astype(np.float32)
        freqs = np.fft.rfftfreq(WINDOW, 1 / sample_rate)
        self._band_masks = {k: (freqs >= lo) & (freqs < hi) for k, (lo, hi) in BANDS.items()}
        self._kick_mask = (freqs >= 30) & (freqs < 150)
        self._prev_mag = None
        self._prev_lin = None
        # floors keep a quiet room from being amplified to full scale (measured: -54 dBFS noise stays < 0.2)
        self._followers = {
            "rms": _Follower(8.0, 0.02),
            "low": _Follower(8.0, 0.5),
            "mid": _Follower(8.0, 0.5),
            "high": _Follower(8.0, 0.5),
            "onset": _Follower(8.0, 20.0),
            "kick": _Follower(8.0, 5.0),
        }
        self._flux_hist: deque[float] = deque(maxlen=max(8, int(0.5 / HOP_SECONDS)))
        self.levels = dict.fromkeys(FEATURE_NAMES, 0.0)
        self._smooth_energy = 0.0
        n_hist = int(TEMPO_HISTORY * self.frame_rate)
        self._onset_hist: deque[float] = deque([0.0] * n_hist, maxlen=n_hist)
        self.t = 0.0  # analysed audio time in seconds
        self.onsets: deque[float] = deque(maxlen=64)
        self._last_onset = -1.0
        self.bpm = 120.0
        self._period = 0.5
        self._beat_anchor = 0.0  # time of a beat
        self._beat_anchor_index = 0.0
        self._last_tempo = 0.0
        self.duration = float("inf")
        self.sections: list[Section] = []
        self.started = time.monotonic()

    # ---- input ----
    def feed(self, samples: np.ndarray) -> None:
        """Mono float samples in arrival order (called from the audio thread)."""
        with self._lock:
            data = np.concatenate([self._pending, np.asarray(samples, np.float32).ravel()])
            n = len(data) // self.hop
            for i in range(n):
                self._process(data[i * self.hop : (i + 1) * self.hop])
            self._pending = data[n * self.hop :]

    def _process(self, hop: np.ndarray) -> None:
        dt = self.hop / self.sr
        self._buf = np.concatenate([self._buf[len(hop) :], hop])
        self.t += dt
        mag = np.abs(np.fft.rfft(self._buf * self._window))
        f = self._followers
        self.levels["rms"] = f["rms"].norm(float(np.sqrt(np.mean(self._buf**2))), dt)
        for k, m in self._band_masks.items():
            # subtract the log-spectrum floor of a quiet input (~0.6) so silence reads as 0
            self.levels[k] = f[k].norm(max(0.0, float(np.log1p(mag[m].mean() * 10)) - 0.6), dt)
        logmag = np.log1p(mag)
        rise = np.zeros_like(logmag) if self._prev_mag is None else np.maximum(logmag - self._prev_mag, 0)
        self._prev_mag = logmag
        flux = float(rise.sum())
        # relative to the recent median: noise has a high but steady flux, onsets stick out
        self._flux_hist.append(flux)
        onset = f["onset"].norm(max(0.0, flux - float(np.median(self._flux_hist))), dt)
        self.levels["onset"] = onset
        # beat signal: kicks carry the beat far more often than hi-hats or off-beat bass; measured on the
        # linear spectrum so the loud kick outweighs a quieter bass line in the same band
        lin = mag[self._kick_mask]
        kick_rise = 0.0 if self._prev_lin is None else float(np.maximum(lin - self._prev_lin, 0).sum())
        self._prev_lin = lin
        kick = f["kick"].norm(kick_rise, dt)
        self._onset_hist.append(0.5 * onset + 2.0 * kick)
        hist = np.fromiter(self._onset_hist, float)
        recent = hist[-int(0.5 * self.frame_rate) :]
        thresh = recent.mean() + 1.5 * recent.std()
        if flux > thresh and flux > 1e-6 and self.t - self._last_onset > 0.1:
            self.onsets.append(self.t)
            self._last_onset = self.t
        self._smooth_energy += (self.levels["rms"] - self._smooth_energy) * min(1.0, dt / 4.0)
        if self.t - self._last_tempo > 0.5:
            self._last_tempo = self.t
            self._update_tempo(hist)

    def _update_tempo(self, hist: np.ndarray) -> None:
        x = hist - hist.mean()
        if not np.any(x):
            return
        ac = np.correlate(x, x, mode="full")[len(x) - 1 :]
        lags = np.arange(len(ac)) / self.frame_rate
        valid = (lags >= 60 / MAX_BPM) & (lags <= 60 / MIN_BPM)
        if not valid.any():
            return
        bpms = 60 / lags[valid]
        prior = np.exp(-0.5 * (np.log2(bpms / 120.0) / 0.9) ** 2)  # log-normal preference around 120 BPM
        score = ac[valid] / (ac[0] + 1e-9) * prior
        if score.max() < 0.05:
            return
        k = int(np.flatnonzero(valid)[int(np.argmax(score))])
        # parabolic interpolation: sub-frame lag, otherwise the tempo is quantised to the hop size
        if 0 < k < len(ac) - 1:
            a0, a1, a2 = ac[k - 1], ac[k], ac[k + 1]
            denom = a0 - 2 * a1 + a2
            k = k + (0.5 * (a0 - a2) / denom if denom < 0 else 0.0)
        period = float(k / self.frame_rate)
        # phase: offset whose comb best matches the onset curve of the last 4 s
        n = int(4 * self.frame_rate)
        seg = hist[-n:]
        step = period * self.frame_rate
        best, best_phase = -1.0, 0.0
        for ph in np.linspace(0, step, 24, endpoint=False):
            idx = (len(seg) - 1 - ph - np.arange(0, len(seg), step)).astype(int)
            idx = idx[(idx >= 0) & (idx < len(seg))]
            s = seg[idx].sum()
            if s > best:
                best, best_phase = s, ph
        anchor = self.t - best_phase / self.frame_rate
        # continue the beat count smoothly from the previous grid
        prev_index = self._beat_index_at(anchor)
        self._period = 0.7 * self._period + 0.3 * period if abs(period - self._period) < 0.08 * self._period else period
        self.bpm = 60.0 / self._period
        self._beat_anchor = anchor
        self._beat_anchor_index = float(round(prev_index))

    def _beat_index_at(self, t: float) -> float:
        return self._beat_anchor_index + (t - self._beat_anchor) / self._period

    # ---- AudioFeatures interface ----
    @property
    def beat_period(self) -> float:
        return self._period

    def level(self, name: str, t: float) -> float:
        if name == "rms":
            return self.levels["rms"]
        return self.levels.get(name, 0.0)

    def beat_position(self, t: float) -> float:
        return max(0.0, self._beat_index_at(t))

    def bar_position(self, t: float) -> float:
        return self.beat_position(t) / 4.0

    def section_at(self, t: float):
        return None

    def recent(self, kind: str, t: float, window: float) -> np.ndarray:
        if kind == "onset":
            return np.array([o for o in self.onsets if t - window <= o <= t])
        period = self._period * (4 if kind == "bar" else 1)
        pos = self.beat_position(t) / (4 if kind == "bar" else 1)
        last = t - (pos % 1.0) * period
        marks = last - np.arange(int(window / period) + 1) * period
        return marks[marks >= t - window][::-1]

    def frame(self, t: float) -> AudioFrame:
        beat = self.beat_position(t)
        bar = beat / 4.0
        onsets = [o for o in self.onsets if o <= t]
        return AudioFrame(
            t=t,
            bpm=self.bpm,
            rms=self.levels["rms"],
            low=self.levels["low"],
            mid=self.levels["mid"],
            high=self.levels["high"],
            onset=self.levels["onset"],
            beat=beat,
            beat_phase=beat % 1.0,
            bar=bar,
            bar_phase=bar % 1.0,
            since_beat=(beat % 1.0) * self._period,
            since_bar=(bar % 1.0) * 4 * self._period,
            since_onset=t - onsets[-1] if onsets else float("inf"),
            section="live",
            section_label="L",
            section_energy=self._smooth_energy,
        )


class LiveInput:
    """Microphone / line-in capture feeding LiveAudioFeatures (sounddevice)."""

    def __init__(self, device: int | str | None = None, sample_rate: int | None = None):
        import sounddevice as sd

        info = sd.query_devices(device, kind="input")
        self.device_name = info["name"]
        self.sr = int(sample_rate or info["default_samplerate"] or 44100)
        self.features = LiveAudioFeatures(self.sr)
        self._stream = sd.InputStream(
            device=device, channels=1, samplerate=self.sr, blocksize=self.features.hop, dtype="float32", callback=self._callback
        )
        self._stream.start()

    def _callback(self, indata, frames, time_info, status) -> None:
        self.features.feed(indata[:, 0].copy())

    def time(self) -> float:
        return self.features.t

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()


DESKTOP = "desktop"  # device id prefix for the PC's sound output ("desktop" or "desktop:<speaker>")


class LoopbackInput:
    """What the PC plays (browser, Spotify, ...) via WASAPI loopback - no microphone needed.

    Uses the `soundcard` package; sounddevice's PortAudio build has no loopback devices.
    WASAPI delivers no data while nothing plays, so silence is filled in to keep the show
    clock running."""

    def __init__(self, speaker: str | None = None, sample_rate: int = 48000):
        import soundcard as sc

        spk = sc.get_speaker(speaker) if speaker else sc.default_speaker()
        self._mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
        self.device_name = f"Desktop-Sound: {spk.name}"
        self.sr = sample_rate
        self.features = LiveAudioFeatures(self.sr)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._last = time.monotonic()
        self._error: str | None = None
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self._thread.start()
        self._filler = threading.Thread(target=self._fill, daemon=True)
        self._filler.start()
        ready.wait(5.0)
        if self._error:
            self.close()
            raise RuntimeError(self._error)

    def _feed(self, samples: np.ndarray) -> None:
        with self._lock:
            self.features.feed(samples)
            self._last = time.monotonic()

    def _run(self, ready: threading.Event) -> None:
        import warnings

        warnings.filterwarnings("ignore", message=".*discontinuity.*")
        try:
            with self._mic.recorder(samplerate=self.sr, channels=2, blocksize=self.features.hop) as rec:
                ready.set()
                while not self._stop.is_set():
                    data = rec.record(numframes=self.features.hop)
                    if len(data):
                        self._feed(np.ascontiguousarray(data.mean(axis=1), dtype=np.float32))
        except Exception as exc:  # device gone, exclusive mode, ...
            self._error = f"Desktop-Sound nicht verfügbar: {exc}"
            ready.set()

    def _fill(self) -> None:
        while not self._stop.wait(0.05):
            gap = time.monotonic() - self._last
            if gap > 0.1:
                self._feed(np.zeros(int(gap * self.sr), np.float32))

    def time(self) -> float:
        return self.features.t

    def close(self) -> None:
        self._stop.set()


def open_input(device: int | str | None):
    """LiveInput for a sound card input, LoopbackInput for "desktop[:speaker]"."""
    if isinstance(device, str) and device.startswith(DESKTOP):
        return LoopbackInput(device.partition(":")[2] or None)
    if isinstance(device, str) and device.isdigit():
        device = int(device)
    return LiveInput(device)


class FileInput:
    """Plays a file into the analyser at real-time speed (demo / tests, no sound output)."""

    def __init__(self, path, loop: bool = True):
        import soundfile as sf

        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        self.device_name = f"Datei: {path}"
        self.sr = sr
        self.data = data.mean(axis=1)
        self.features = LiveAudioFeatures(sr)
        self.loop = loop
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        pos, block = 0, self.features.hop * 4
        start = time.monotonic()
        while not self._stop.is_set():
            target = int((time.monotonic() - start) * self.sr)
            while pos < target:
                chunk = self.data[pos % len(self.data) : pos % len(self.data) + block]
                if not len(chunk):
                    chunk = self.data[:block]
                self.features.feed(chunk)
                pos += len(chunk)
                if not self.loop and pos >= len(self.data):
                    return
            time.sleep(0.005)

    def time(self) -> float:
        return self.features.t

    def close(self) -> None:
        self._stop.set()


def desktop_devices() -> list[dict]:
    """The PC's sound outputs that can be captured (loopback)."""
    try:
        import soundcard as sc

        default = sc.default_speaker().name
        return [
            {
                "index": f"{DESKTOP}:{s.name}",
                "name": f"Desktop-Sound – {s.name}",
                "channels": 2,
                "default": False,
                "kind": "desktop",
                "default_output": s.name == default,
            }
            for s in sc.all_speakers()
        ]
    except Exception:  # no soundcard package / not supported on this system
        return []


def input_devices() -> list[dict]:
    """Desktop sound (loopback) first, then microphones and line inputs."""
    out = desktop_devices()
    try:
        import sounddevice as sd

        apis = sd.query_hostapis()
        # Windows lists every device once per audio API; WASAPI has the full names
        wasapi = next((i for i, h in enumerate(apis) if "WASAPI" in h["name"]), None)
        default = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) else None
        default_name = sd.query_devices(default)["name"] if default is not None and default >= 0 else None
        seen = set()
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] <= 0 or (wasapi is not None and d["hostapi"] != wasapi):
                continue
            name = _clean_name(d["name"])
            if name in seen:
                continue
            seen.add(name)
            is_default = i == default or (default_name is not None and default_name.startswith(name[:31]))
            out.append({"index": i, "name": name, "channels": d["max_input_channels"], "default": is_default, "kind": "input"})
    except Exception:
        pass
    return out


def _clean_name(name: str) -> str:
    """Readable name for Bluetooth hands-free devices ('...%1 Hands-Free%0 ;(Phone))' -> 'Hands-Free (Phone)')."""
    m = re.search(r"%1 (.*?)%0.*?\((.*?)\)\)?\s*$", name, re.S)
    if m:
        return f"{m.group(1).strip()} ({m.group(2).strip()})"
    return " ".join(name.split())
