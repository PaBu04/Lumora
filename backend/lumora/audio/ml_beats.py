"""Optional neural beat/downbeat tracking with beat_this (CPJKU, ISMIR 2024).

Install with `pip install -e ".[ml]"`. The model weights (~80 MB) are downloaded from
the authors' server on first use. When anything is missing the caller falls back to the
librosa based tracker.
"""

import logging
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)
_lock = threading.Lock()
_model = None
_error: str | None = None


def installed() -> bool:
    try:
        import beat_this.inference  # noqa: F401
    except Exception:
        return False
    return True


def status() -> dict:
    return {"installed": installed(), "loaded": _model is not None, "error": _error}


def _load():
    global _model, _error
    with _lock:
        if _model is None:
            from beat_this.inference import File2Beats

            try:
                _model = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)
                _error = None
            except Exception as exc:  # weights not downloadable, broken install ...
                _error = f"{type(exc).__name__}: {exc}"
                raise
    return _model


def track(path: Path | str) -> tuple[np.ndarray, np.ndarray]:
    """Beat and downbeat times in seconds."""
    beats, downbeats = _load()(str(path))
    return np.asarray(beats, dtype=np.float64), np.asarray(downbeats, dtype=np.float64)
