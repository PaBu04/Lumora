"""Source separation: drums, bass, vocals and the rest ("other": keys, synths, guitars ...).

Uses Hybrid Demucs (Défossez 2021) as shipped with torchaudio (HDEMUCS_HIGH_MUSDB_PLUS):
about 45 s for a 4 minute song on a CPU; the weights (~320 MB) are downloaded on first use.
Without torch / torchaudio a harmonic-percussive split approximates drums / bass / other
(no vocals).
"""

import logging
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)
STEMS = ("drums", "bass", "vocals", "other")
MODEL_SR = 44100
SEGMENT = 10.0  # seconds per model call
OVERLAP = 0.5  # seconds cross-faded between calls

_lock = threading.Lock()
_model = None
_error: str | None = None


def installed() -> bool:
    try:
        import torch  # noqa: F401
        import torchaudio.pipelines as pipelines
    except Exception:
        return False
    return hasattr(pipelines, "HDEMUCS_HIGH_MUSDB_PLUS")


def status() -> dict:
    return {"installed": installed(), "loaded": _model is not None, "error": _error}


def _load():
    global _model, _error
    with _lock:
        if _model is None:
            from torchaudio.pipelines import HDEMUCS_HIGH_MUSDB_PLUS

            try:
                _model = HDEMUCS_HIGH_MUSDB_PLUS.get_model().eval()
                _error = None
            except Exception as exc:  # weights not downloadable ...
                _error = f"{type(exc).__name__}: {exc}"
                raise
    return _model


def separate(path: Path | str, sr: int, progress: Callable[[float], None] | None = None) -> dict[str, np.ndarray]:
    """Mono stems at sample rate `sr`, aligned with librosa.load(path, sr=sr)."""
    import librosa
    import torch

    model = _load()
    y, _ = librosa.load(path, sr=MODEL_SR, mono=False)
    if y.ndim == 1:
        y = np.stack([y, y])
    wav = torch.from_numpy(np.ascontiguousarray(y[:2])).float()
    ref = wav.mean(0)
    mean, std = float(ref.mean()), float(ref.std()) or 1.0
    wav = (wav - mean) / std
    n = wav.shape[1]
    seg, ov = int(SEGMENT * MODEL_SR), int(OVERLAP * MODEL_SR)
    sources = list(model.sources)
    out = torch.zeros(len(sources), n)
    weight = torch.zeros(n)
    with torch.inference_mode():
        s = 0
        while s < n:
            e = min(n, s + seg)
            chunk = wav[:, s:e]
            if chunk.shape[1] < seg:
                chunk = torch.nn.functional.pad(chunk, (0, seg - chunk.shape[1]))
            res = model(chunk[None])[0][:, :, : e - s].mean(1)  # (sources, samples), mono
            fade = torch.ones(e - s)
            if s > 0:
                fade[: min(ov, e - s)] = torch.linspace(0, 1, ov)[: e - s]
            if e < n:
                fade[-ov:] = torch.linspace(1, 0, ov)
            out[:, s:e] += res * fade
            weight[s:e] += fade
            if progress:
                progress(e / n)
            if e == n:
                break
            s = e - ov
    out = (out / weight.clamp(min=1e-6) * std).numpy()
    return {name: librosa.resample(out[i], orig_sr=MODEL_SR, target_sr=sr) for i, name in enumerate(sources)}


def approximate(y: np.ndarray, sr: int) -> dict[str, np.ndarray]:
    """Fallback without a separation model: percussive part = drums, harmonic part split at
    200 Hz into bass and other. There are no vocals."""
    import librosa

    stft = librosa.stft(y, n_fft=2048, hop_length=512)
    harm, perc = librosa.decompose.hpss(stft, margin=2.0)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    low = (freqs < 200)[:, None]
    n = len(y)
    return {
        "drums": librosa.istft(perc, hop_length=512, length=n),
        "bass": librosa.istft(harm * low, hop_length=512, length=n),
        "other": librosa.istft(harm * ~low, hop_length=512, length=n),
    }
