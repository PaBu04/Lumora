"""AI show generation inside the app via the local Claude Code CLI.

Runs `claude -p` (headless) with the user's own Claude Code login, so a Claude Pro/Max
subscription covers it - no API key or API credits are involved (do NOT use --bare, which
would require an API key). Claude only gets the tools of this app's MCP server
(`--strict-mcp-config`, `--permission-mode dontAsk`): no shell, no file access.
"""

import asyncio
import json
import os
import shlex
import shutil
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

TOOL_LABELS = {
    "get_overview": "Projekt und Raum gelesen",
    "get_song_analysis": "Songanalyse gelesen",
    "get_song_events": "Noten und Schläge gelesen",
    "analyze_light": "Helligkeit und Kontrast geprüft",
    "WebSearch": "Im Internet recherchiert",
    "get_led_positions": "LED-Positionen gelesen",
    "list_effects": "Effekte nachgeschlagen",
    "get_show_format": "Show-Format nachgeschlagen",
    "list_shows": "Shows aufgelistet",
    "get_show": "Show gelesen",
    "create_show": "Show angelegt",
    "update_show": "Show neu geschrieben",
    "add_clips": "Clips hinzugefügt",
    "update_clips": "Clips geändert",
    "remove_clips": "Clips entfernt",
    "validate": "Show geprüft",
    "analyze_power": "Strombedarf geprüft",
    "write_shader": "Eigenen Effekt geschrieben",
    "get_shader_api": "Shader-Doku gelesen",
    "render_snapshot": "Bild aus Betrachtersicht gerendert",
    "render_timeline": "Timeline-Bild gerendert",
    "preview": "Vorschau gestartet",
    "playback": "Wiedergabe gesteuert",
    "list_show_versions": "Versionen angesehen",
    "restore_show_version": "Version wiederhergestellt",
    "ToolSearch": "Werkzeuge geladen",
}


def claude_command() -> list[str] | None:
    """Command that starts Claude Code (LSG_CLAUDE_CMD overrides, e.g. for tests)."""
    override = os.environ.get("LSG_CLAUDE_CMD")
    if override:
        # non-POSIX splitting keeps quotes around Windows paths - strip them
        return [t.strip('"') for t in shlex.split(override, posix=os.name != "nt")]
    exe = shutil.which("claude")
    if not exe:
        for candidate in (Path.home() / ".local" / "bin" / "claude.exe", Path.home() / ".local" / "bin" / "claude"):
            if candidate.is_file():
                exe = str(candidate)
                break
    return [exe] if exe else None


async def claude_status() -> dict:
    cmd = claude_command()
    if not cmd:
        return {"installed": False, "version": None}
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=_child_env()
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        return {"installed": proc.returncode == 0, "version": out.decode(errors="replace").strip() or None}
    except (OSError, TimeoutError):
        return {"installed": False, "version": None}


def _child_env() -> dict:
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)  # allow starting it from a shell that itself runs inside Claude Code
    env.pop("ANTHROPIC_API_KEY", None)  # always use the subscription login, never paid API credits
    return env


def build_prompt(project: str, song: dict | None, request: str, show_name: str, show_id: str | None) -> str:
    song_line = (
        f'Song: "{song["title"]}" (song_id {song["id"]}, Dauer {song["duration"]:.0f} s).' if song else "Kein Song gewählt."
    )
    if show_id:
        task = (
            f"Überarbeite die bestehende Show mit show_id {show_id} (lies sie zuerst mit get_show). "
            "Ändere gezielt mit add_clips / update_clips / remove_clips."
        )
    else:
        task = (
            f'Lege eine neue Show mit create_show an (name "{show_name}"'
            + (f', song_id "{song["id"]}"' if song else "")
            + ") und fülle sie mit add_clips."
        )
    return f"""Du programmierst in der App "Light Show Generator" eine LED-Lichtshow - ausschließlich über die
Werkzeuge des MCP-Servers "lightshow". Projekt: {project}. {song_line}

Wunsch des Nutzers:
{request.strip()}

{task}

Vorgehen:
1. get_overview (Raum, Strips mit Länge und Sichtbarkeit, Betrachter, Helligkeit, Strombudget) und
   get_song_analysis (Abschnitte, welche Instrumente wann tragen, Drops, Build-ups, Fills, Crashes,
   Gesangsphrasen). Bei Bedarf get_song_events für einzelne Noten und Schläge eines Instruments.
   Wenn du den Song nicht kennst, darfst du ihn kurz im Internet recherchieren (WebSearch: Stimmung,
   Instrumente, bekannte Stellen) - höchstens 2 Suchen.
2. Erst planen: Was trägt das Stück in jedem Abschnitt (Gesang, Lead-Synth, Bass, Drums)? Welcher Strip zeigt
   welches Instrument? Welche Strips sieht der Betrachter direkt (Details), welche liegen hinter/neben ihm
   (Raumfarbe, Blitze bei Drops)? Welche Farben pro Abschnitt? Wo sind die großen Momente?
3. Show aufbauen - halte dich an die Regeln aus den Server-Anweisungen: Folge den Instrumenten statt einem
   starren Raster ("hits" auf kick/snare, "notes" auf vocal/lead/bass, Trigger auf Instrumentenspuren);
   setze einmalige Cues (trigger "once") auf Drops, Build-ups ("rise" bis zum Drop), Fills ("sweep" über
   den Fill) und Crashes; leise Stellen fast dunkel, laute Stellen mit hellen Akzenten, "dynamics" der
   Show auf 0.5-0.8; Muster in Metern (Achse "s"); lange Strips nur sparsam und gedimmt fluten.
4. validate und analyze_light aufrufen: Fehler beheben; room_light etwa 0.002-0.03, leise Passagen unter
   0.008, deutlicher Kontrast zwischen dunklen und hellen Stellen, keine langen Stellen ohne Bewegung;
   bei Strombudgets analyze_power beachten.
5. Mit render_timeline (ganzer Song oder Abschnitte) prüfen, ob Rhythmus, Abwechslung und Übergänge passen;
   ggf. nachbessern.
6. Zum Schluss preview mit der show_id starten.
Antworte am Ende mit 3 bis 6 Sätzen auf Deutsch, was die Show macht."""


@dataclass
class AgentRun:
    id: str
    project: str
    prompt: str
    started: float = field(default_factory=time.time)
    status: str = "running"  # running | done | error | cancelled
    events: list[dict] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    show_ids: list[str] = field(default_factory=list)
    turns: int | None = None
    duration_s: float | None = None
    model: str | None = None

    def add(self, kind: str, text: str, **extra) -> None:
        self.events.append({"kind": kind, "text": text, "time": round(time.time() - self.started, 1), **extra})

    def to_dict(self) -> dict:
        d = asdict(self)
        d["events"] = self.events[-200:]
        return d


def parse_line(run: AgentRun, line: str) -> None:
    """Apply one stream-json line from `claude -p --output-format stream-json` to the run."""
    try:
        msg = json.loads(line)
    except ValueError:
        return
    kind = msg.get("type")
    if kind == "system" and msg.get("subtype") == "init":
        run.model = msg.get("model")
        servers = {s.get("name"): s.get("status") for s in msg.get("mcp_servers", [])}
        state = servers.get("lightshow")
        run.add("info", f"Claude gestartet ({run.model or 'Modell unbekannt'}), Verbindung zur App: {state or 'unbekannt'}")
        if state not in (None, "connected"):
            run.add("error", "Claude erreicht den MCP-Server der App nicht - läuft die App auf dem erwarteten Port?")
    elif kind == "assistant":
        for block in msg.get("message", {}).get("content", []):
            if block.get("type") == "text" and block.get("text", "").strip():
                run.add("text", block["text"].strip())
            elif block.get("type") == "tool_use":
                name = str(block.get("name", "")).split("__")[-1]
                args = block.get("input") or {}
                detail = ""
                if name in ("add_clips",) and isinstance(args.get("clips"), list):
                    detail = f"{len(args['clips'])} Clips in Ebene „{args.get('layer', '?')}“"
                elif name in ("render_timeline",) and "start" in args:
                    detail = f"{args.get('start', 0)}-{args.get('end', '?')} s"
                elif name == "create_show":
                    detail = str(args.get("name", ""))
                run.add("tool", TOOL_LABELS.get(name, name), tool=name, detail=detail)
    elif kind == "user":
        for block in msg.get("message", {}).get("content", []):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                text = _result_text(block)
                if '"show_id"' in text:
                    try:
                        sid = json.loads(text).get("show_id")
                        if sid and sid not in run.show_ids:
                            run.show_ids.append(sid)
                    except ValueError:
                        pass
                if block.get("is_error"):
                    run.add("warn", f"Werkzeug-Fehler: {text[:200]}")
    elif kind == "result":
        run.turns = msg.get("num_turns")
        run.duration_s = round((msg.get("duration_ms") or 0) / 1000, 1)
        if msg.get("is_error") or msg.get("subtype") != "success":
            run.status = "error"
            run.error = str(msg.get("result") or msg.get("subtype") or "Fehler")
        else:
            run.status = "done"
            run.result = msg.get("result")
            # the final answer is also the last assistant message - show it only once
            if run.events and run.events[-1]["kind"] == "text" and run.events[-1]["text"] == (run.result or "").strip():
                run.events.pop()


def _result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


class AgentManager:
    def __init__(self, data_dir: Path, mcp_url: str, notify):
        self.data_dir = data_dir
        self.mcp_url = mcp_url
        self.notify = notify  # async callable(dict) -> broadcast to the UI
        self.current: AgentRun | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task | None = None

    @property
    def busy(self) -> bool:
        return self.current is not None and self.current.status == "running"

    async def start(self, project: str, song: dict | None, request: str, show_name: str, show_id: str | None) -> AgentRun:
        if self.busy:
            raise RuntimeError("Es läuft bereits eine KI-Generierung")
        cmd = claude_command()
        if not cmd:
            raise FileNotFoundError("Claude Code (claude) wurde nicht gefunden")
        work = self.data_dir / "ai_workspace"
        work.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="lsg-mcp-", suffix=".json", dir=work)
        os.close(fd)  # Windows cannot delete files with an open handle
        cfg = Path(name)
        cfg.write_text(json.dumps({"mcpServers": {"lightshow": {"type": "http", "url": self.mcp_url}}}), encoding="utf-8")
        run = AgentRun(id=uuid.uuid4().hex[:10], project=project, prompt=request)
        self.current = run
        args = [
            *cmd,
            "-p",
            build_prompt(project, song, request, show_name, show_id),
            "--output-format",
            "stream-json",
            "--verbose",
            "--mcp-config",
            str(cfg),
            "--strict-mcp-config",
            "--allowedTools",
            "mcp__lightshow,WebSearch",
            "--permission-mode",
            "dontAsk",
            "--no-session-persistence",
        ]
        run.add("info", "Starte Claude Code …")
        await self._publish()
        self._task = asyncio.create_task(self._run(args, run, cfg, work))
        return run

    async def _run(self, args: list[str], run: AgentRun, cfg: Path, work: Path) -> None:
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(work),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_child_env(),
                limit=16 * 1024 * 1024,
            )
            assert self._proc.stdout is not None
            async for raw in self._proc.stdout:
                parse_line(run, raw.decode("utf-8", errors="replace"))
                await self._publish()
            stderr = (await self._proc.stderr.read()).decode(errors="replace") if self._proc.stderr else ""
            code = await self._proc.wait()
            if run.status == "running":
                run.status = "cancelled" if code in (-15, 1) and run.error == "abgebrochen" else "error"
                run.error = run.error or (stderr.strip()[-500:] or f"Claude Code beendet mit Code {code}")
                if "login" in (run.error or "").lower() or "auth" in (run.error or "").lower():
                    run.error += " - bitte einmal `claude` im Terminal starten und anmelden."
        except asyncio.CancelledError:
            run.status = "cancelled"
            raise
        except Exception as exc:
            run.status, run.error = "error", f"{type(exc).__name__}: {exc}"
        finally:
            cfg.unlink(missing_ok=True)
            self._proc = None
            await self._publish()

    async def cancel(self) -> None:
        if self._proc and self.busy:
            self.current.error = "abgebrochen"
            self.current.status = "cancelled"
            self._proc.terminate()
            await self._publish()

    async def shutdown(self) -> None:
        """Stop a running generation when the app exits."""
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()

    async def _publish(self) -> None:
        if self.current:
            await self.notify({"kind": "ai", "run": self.current.to_dict()})
