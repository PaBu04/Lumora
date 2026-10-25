# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Lumora: music-synchronised LED light shows for WLED controllers. Python/FastAPI backend (`backend/lumora`), React +
Three.js frontend (`frontend/`). The README (German) is the user-facing feature list and setup guide.

## Commands

Backend (run from `backend/`, venv at `backend/.venv`, Windows paths):

```powershell
.venv\Scripts\python -m pip install -e ".[dev]"        # ".[ml]" adds torch/demucs/beat_this (~1 GB)
.venv\Scripts\python -m pytest                          # default run excludes the ui and ml markers
.venv\Scripts\python -m pytest tests/test_render.py::test_name   # single test
.venv\Scripts\python -m pytest -m ui                    # Playwright browser tests; need frontend/dist built
.venv\Scripts\python -m pytest -m ml                    # real Demucs / neural models
.venv\Scripts\python -m ruff check lumora tests
.venv\Scripts\python -m ruff format --check lumora tests   # CI enforces formatting too
.venv\Scripts\lumora                                    # server on http://127.0.0.1:8000
.venv\Scripts\lumora-wled-sim --leds 600 --http 8081 [--pins 2]   # fake WLED (mDNS, DDP, /sim/stats)
```

Frontend (run from `frontend/`): `npm run dev` (Vite on :5173, proxies `/api`, `/mcp`, `/ws` to the backend;
`LUMORA_BACKEND` overrides the target), `npm run build`, `npm run lint`, `npm run typecheck`.
`node scripts/extract-strings.mjs --missing` lists German UI texts without an English translation.

`start.ps1` at the repo root sets up the venv, builds the UI on first run and starts the app.

CI (`.github/workflows/ci.yml`) runs on Python 3.12 and 3.14 with `LUMORA_AUDIO=null`. The local venv is 3.14,
which evaluates annotations lazily, so 3.12-only failures don't show locally. Example: a class that defines a
`list()` method and then annotates `list[str]` breaks on 3.12/3.13. Such modules need
`from __future__ import annotations`.

## Architecture

**One render path.** `render/engine.py` (`Renderer`) turns Show × LED table × time into a perceived-RGB frame.
The browser preview, live DDP output, FSEQ/video export and the AI's snapshots all use it, so they always match.
Don't add a second rendering path for any of them.

**Frame flow.** `playback/session.py` (`PlaybackSession`) owns the clock-driven loop. Each `_tick` reads the audio
clock (minus audio latency), renders once, and serves every consumer that is due:
- the browser at `UI_FPS`, as a binary WebSocket message (`<dI` header: time + LED count, then RGB bytes; parsed in
  `frontend/src/ws.ts` into `liveFrame`, which render loops read without going through React state)
- in live mode, each controller on its own rate via `output/link.py`

Controllers get frames through `output/pipeline.py`: master brightness → calibration curve (perceived → PWM) → RGBW
split → power limiting per controller/project → dithering → bytes → `output/ddp.py`. Per-controller rate comes from
the WLED LED config (data pins limit FPS; see `output/wled.py`). Unchanged frames are skipped except for keep-alives.

**Model → geometry.** Pydantic models in `model/` (Project = room, fixtures, controllers, calibration, viewer;
Show = layers of clips with effect, params and target). `geometry/led_table.py` expands fixtures into a flat
`LedTable` (positions, normalised and viewer-relative coordinates, `view` = how directly the viewer sees each LED).
Clip targets select LEDs by fixture, tag, coordinate ranges and `view` (`engine.select_leds`).

**Effects and params.** `render/effects.py` holds the `EFFECTS` registry. Each effect returns `(rgb, alpha)` for
its LEDs and declares `Param`s. A param value can be static, audio-bound, LFO or keyframes (`render/params.py`).
Triggers come from the beat grid or the instrument tracks built in `audio/`. Custom effects are Python/numpy shaders
(`render/shaders.py`, static checks) that run in a worker process (`render/shader_host.py`, killed on timeout).
`render/safety.py` caps large flashes per second for preview, output and export.

**Audio analysis** (`audio/`) runs in a single-thread pool started from `AppState` and resumes after a restart.
`audio/library.py` stores `data/songs/<id>/{song.json, audio.*, analysis.json}`. Stem separation falls back from
Demucs 6-stem → Hybrid Demucs → harmonic/percussive approximation (`LUMORA_STEMS`). `render/autoshow.py` builds
starter shows from instruments + song form.

**Shared state.** `state.py` (`AppState`) is created in `app.create_app` and shared by REST (`api.py`, router at
`/api`), the WebSocket (`/ws`), the MCP server (`/mcp`) and the phone remote (`remote.py`, separate port 8010).
After a write, call `st.project_changed(slug)` / `st.show_changed(slug, id)`. That hot-reloads the session and
broadcasts an event, and the frontend (`ws.ts` → zustand `store.ts`) then refetches.

**Storage.** Everything is JSON under `LUMORA_DATA` (default `./data`, gitignored), written with
`atomic_write_text` (retries for files Windows locks briefly). `storage/history.py` keeps a version per save:
rapid UI saves coalesce within 60 s, AI edits always get their own version so each can be rolled back.

**AI.** `ai_agent.py` runs the user's local `claude -p` CLI (subscription, never an API key: `ANTHROPIC_API_KEY`
is ignored on purpose, and never pass `--bare`). It uses `--strict-mcp-config` with only the app's MCP server
(`lightshow`) plus WebSearch, so Claude gets no shell or file access. `mcp_server.py` defines those tools, and its
`INSTRUCTIONS` string is the show-design guidance given to the model. Tests swap the CLI for `tests/fake_claude.py`.

## Conventions

- Code, comments, docstrings and commit messages are in English. The UI is German first. In the frontend the German
  text is the i18n key (`t("Speichern")`), and its English translation goes in `frontend/src/i18n/en.ts`.
  `i18n/dom.ts` also translates rendered DOM text. Help/manual entries in `help.ts` are `{de, en}` pairs. When you
  add UI text, add the English entry and check with `extract-strings.mjs --missing`.
- Brightness values in shows and effects are *perceived* lightness (0.5 looks half as bright). Conversion to PWM
  happens only in the output pipeline and calibration.
- Ruff: line length 130, target py312. German typographic characters are allowed (RUF001-003 ignored).
- Tests use `LUMORA_STEMS=approx` and stub out the Demucs check (`tests/conftest.py`). Integration and UI tests
  start a real uvicorn server plus `wled_sim` on free ports. They poll for conditions (`until(...)`) instead of
  using fixed sleeps, so keep new timing-dependent tests that way.
- Test against `lumora-wled-sim`. Don't send live output to real WLED controllers on the LAN unless the user asks.
