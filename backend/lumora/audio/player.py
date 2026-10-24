"""Audio playback whose position is the master clock of the show.

DevicePlayer plays through the sound card (sounddevice / PortAudio) and reports the
position of the sample that is audible right now (output latency compensated via the
DAC timestamps). NullPlayer is a silent wall clock for headless use and tests.
"""

import logging
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf

log = logging.getLogger(__name__)


class NullPlayer:
    def __init__(self):
        self.duration = 0.0
        self.playing = False
        self._pos = 0.0
        self._t0 = 0.0
        self.path: Path | None = None

    def load(self, path: Path | str | None, duration: float | None = None) -> None:
        self.stop()
        self.path = Path(path) if path else None
        self.duration = duration if duration is not None else (sf.info(str(path)).duration if path else 0.0)
        self._pos = 0.0

    def play(self) -> None:
        if not self.playing and self._pos < self.duration:
            self._t0 = time.perf_counter() - self._pos
            self.playing = True

    def pause(self) -> None:
        if self.playing:
            self._pos = self.time()
            self.playing = False

    def stop(self) -> None:
        self.playing = False
        self._pos = 0.0

    def seek(self, t: float) -> None:
        t = min(max(t, 0.0), self.duration)
        self._pos = t
        self._t0 = time.perf_counter() - t

    def time(self) -> float:
        if not self.playing:
            return self._pos
        t = time.perf_counter() - self._t0
        if t >= self.duration:
            self.playing = False
            self._pos = self.duration
            return self.duration
        return t

    @property
    def finished(self) -> bool:
        return not self.playing and self.duration > 0 and self._pos >= self.duration

    def close(self) -> None:
        self.stop()


class DevicePlayer(NullPlayer):
    def __init__(self):
        super().__init__()
        import sounddevice as sd  # imported lazily: PortAudio may be missing on servers

        self._sd = sd
        self._lock = threading.Lock()
        self._data = np.zeros((0, 2), np.float32)
        self._sr = 44100
        self._frame = 0  # next sample index to hand to the device
        self._anchor: tuple[int, float, float] | None = None  # (sample, dac_time, perf_counter)
        self._stream = None
        self._last = 0.0

    def load(self, path, duration=None) -> None:
        self.stop()
        if path is None:  # show without song: play silence of the given length
            sr = 44100
            data = np.zeros((int((duration or 0.0) * sr), 2), np.float32)
        else:
            data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        with self._lock:
            self._data, self._sr = data[:, :2], sr
            self._frame = 0
            self._anchor = None
        self.path = Path(path) if path else None
        self.duration = len(data) / sr
        self._open(sr)

    def _open(self, sr: int) -> None:
        if self._stream is not None:
            self._stream.close()
        self._stream = self._sd.OutputStream(samplerate=sr, channels=2, dtype="float32", callback=self._callback, latency="low")
        self._stream.start()

    def _callback(self, outdata, frames, time_info, status) -> None:
        with self._lock:
            if not self.playing:
                outdata.fill(0)
                return
            chunk = self._data[self._frame : self._frame + frames]
            outdata[: len(chunk)] = chunk
            outdata[len(chunk) :] = 0
            dac = getattr(time_info, "outputBufferDacTime", 0.0) or 0.0
            self._anchor = (self._frame, dac, time.perf_counter())
            self._frame += frames
            if self._frame >= len(self._data):
                self.playing = False
                self._pos = self.duration

    def play(self) -> None:
        with self._lock:
            if self.playing or self._frame >= len(self._data):
                return
            self._anchor = None
            self._last = self._frame / self._sr
            self.playing = True

    def pause(self) -> None:
        t = self.time()
        with self._lock:
            self.playing = False
            self._frame = int(t * self._sr)
            self._pos = t

    def stop(self) -> None:
        if hasattr(self, "_lock"):
            with self._lock:
                self.playing = False
                self._frame = 0
                self._pos = 0.0

    def seek(self, t: float) -> None:
        t = min(max(t, 0.0), self.duration)
        with self._lock:
            self._frame = int(t * self._sr)
            self._anchor = None
            self._pos = t
            self._last = t

    def time(self) -> float:
        with self._lock:
            if not self.playing:
                return self._pos if self._frame >= len(self._data) else self._frame / self._sr
            anchor = self._anchor
        if anchor is None:
            return self._last
        sample, dac, perf = anchor
        stream_time = self._stream.time if self._stream is not None else 0.0
        if dac > 0 and stream_time > 0:
            # position of the sample reaching the speaker right now
            t = (sample + (stream_time - dac) * self._sr) / self._sr
        else:
            latency = self._stream.latency if self._stream is not None else 0.0
            t = sample / self._sr + (time.perf_counter() - perf) - latency
        t = min(max(t, self._last), self.duration)  # never run backwards
        self._last = t
        return t

    def close(self) -> None:
        self.stop()
        if self._stream is not None:
            self._stream.close()
            self._stream = None


def create_player(kind: str) -> NullPlayer:
    if kind == "device":
        try:
            p = DevicePlayer()
            p._sd.query_devices(kind="output")
            return p
        except Exception as exc:
            log.warning("no audio output device (%s), using silent clock", exc)
    return NullPlayer()
