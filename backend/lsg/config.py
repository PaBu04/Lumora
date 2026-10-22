"""Runtime configuration (environment variables)."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.environ.get("LSG_DATA", REPO_ROOT / "data"))
FRONTEND_DIST = Path(os.environ.get("LSG_FRONTEND", REPO_ROOT / "frontend" / "dist"))
HOST = os.environ.get("LSG_HOST", "127.0.0.1")
PORT = int(os.environ.get("LSG_PORT", "8000"))
# "device" = sound card via sounddevice, "null" = silent wall-clock player (tests, headless)
AUDIO_BACKEND = os.environ.get("LSG_AUDIO", "device")
FPS = float(os.environ.get("LSG_FPS", "50"))
