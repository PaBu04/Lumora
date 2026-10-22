"""Drum hit detection: kick, snare and hi-hat times for hit-based effects.

Each instrument is found as peaks of the spectral flux (rise in log magnitude) in its
frequency band, with an adaptive threshold so quiet passages still produce hits while
sustained sounds do not:
  kick   40-150 Hz
  snare  150-300 Hz body plus 1.5-5 kHz rattle (both must rise; the rattle must be stronger
         than what a hi-hat puts into that band)
  hihat  7 kHz and up
For analyses made before drum detection existed, `from_curves` approximates hits from
the stored low / mid / high loudness curves.
"""

import numpy as np

DRUMS = ("kick", "snare", "hihat")
MIN_GAP = {"kick": 0.12, "snare": 0.12, "hihat": 0.07}  # seconds between two hits of one drum


def _flux(spec: np.ndarray, freqs: np.ndarray, lo: float, hi: float, mean: bool = False) -> np.ndarray:
    """Rise of the linear magnitude in a band (sum or mean over its bins). Linear (not log) so
    that faint leakage of other instruments into a band stays faint."""
    sel = (freqs >= lo) & (freqs < hi)
    if not sel.any():
        return np.zeros(spec.shape[1], np.float32)
    band = spec[sel]
    rise = np.maximum(np.diff(band, axis=1, prepend=band[:, :1]), 0.0)
    return (rise.mean(axis=0) if mean else rise.sum(axis=0)).astype(np.float32)


def pick_peaks(curve: np.ndarray, rate: float, min_gap: float, sensitivity: float = 1.0, strength: float = 0.2) -> np.ndarray:
    """Times of local maxima that stand out from their surroundings and reach `strength` x the
    typical strong hit of the whole song."""
    n = len(curve)
    if n < 3:
        return np.zeros(0)
    w = max(1, round(0.4 * rate))  # local context +-0.4 s
    kernel = np.ones(2 * w + 1) / (2 * w + 1)
    mean = np.convolve(curve, kernel, mode="same")
    spread = np.convolve(np.abs(curve - mean), kernel, mode="same")
    thresh = mean + sensitivity * 1.2 * spread
    is_peak = (curve[1:-1] > curve[:-2]) & (curve[1:-1] >= curve[2:]) & (curve[1:-1] > thresh[1:-1])
    idx = np.flatnonzero(is_peak) + 1
    if len(idx) == 0:
        return np.zeros(0)
    strong = np.percentile(curve[idx], 90)
    idx = idx[curve[idx] >= strength * strong]
    gap = max(1, round(min_gap * rate))
    keep: list[int] = []
    for i in idx[np.argsort(-curve[idx])]:  # strongest first, then suppress neighbours
        if all(abs(i - k) >= gap for k in keep):
            keep.append(int(i))
    return np.sort(np.asarray(keep, dtype=np.float64)) / rate


def _level(spec: np.ndarray, freqs: np.ndarray, lo: float, hi: float) -> np.ndarray:
    sel = (freqs >= lo) & (freqs < hi)
    return spec[sel].mean(axis=0) if sel.any() else np.zeros(spec.shape[1])


def _gate(times: np.ndarray, rate: float, *levels: np.ndarray, frac: float = 0.25) -> np.ndarray:
    """Keep hits after which every given band is really loud (log flux also rises in near-silence)."""
    if len(times) == 0:
        return times
    keep = np.ones(len(times), bool)
    for lv in levels:
        ref = np.percentile(lv, 95) + 1e-12
        i = np.round(times * rate).astype(int)
        after = np.max([lv[np.clip(i + k, 0, len(lv) - 1)] for k in range(4)], axis=0)
        keep &= after >= frac * ref
    return times[keep]


def detect(spec: np.ndarray, freqs: np.ndarray, rate: float) -> dict[str, np.ndarray]:
    """Hit times per drum from a magnitude spectrogram (frequency x frames)."""
    kick = _flux(spec, freqs, 40, 150)
    body = _flux(spec, freqs, 150, 300)
    hat = _flux(spec, freqs, 7000, 20000)
    # snare noise is broadband, hi-hats are tilted to the top: keep only the 1.5-5 kHz rise that is
    # stronger than a hi-hat would put there (per frequency bin)
    rattle = np.maximum(_flux(spec, freqs, 1500, 5000, mean=True) - 0.6 * _flux(spec, freqs, 7000, 20000, mean=True), 0.0)
    # a snare needs both its body and its noisy rattle to be strong at once
    # (bass notes have body but no rattle, hi-hats rattle but no body)
    snare = np.minimum(body / (np.percentile(body, 99) + 1e-12), rattle / (np.percentile(rattle, 99) + 1e-12))
    return {
        # kicks are the strongest low transients of a mix; weaker ones are bass notes
        "kick": pick_peaks(kick, rate, MIN_GAP["kick"], strength=0.6),
        "snare": pick_peaks(snare, rate, MIN_GAP["snare"], strength=0.6),
        "hihat": pick_peaks(hat, rate, MIN_GAP["hihat"], sensitivity=0.8, strength=0.2),
    }


def from_curves(curves: dict[str, np.ndarray], rate: float) -> dict[str, np.ndarray]:
    """Approximate hits from 0..1 band loudness curves (older analyses without drum data)."""

    def rise(name: str) -> np.ndarray:
        c = np.asarray(curves.get(name, np.zeros(1)), dtype=np.float32)
        return np.maximum(np.diff(c, prepend=c[:1]), 0.0)

    return {
        "kick": pick_peaks(rise("low"), rate, MIN_GAP["kick"]),
        "snare": pick_peaks(np.sqrt(rise("mid") * rise("high") + 1e-12), rate, MIN_GAP["snare"]),
        "hihat": pick_peaks(rise("high"), rate, MIN_GAP["hihat"], sensitivity=0.8),
    }
