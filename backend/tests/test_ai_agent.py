import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lsg.ai_agent import AgentRun, build_prompt, parse_line
from lsg.app import create_app

FAKE = Path(__file__).parent / "fake_claude.py"


def test_parse_stream_json():
    run = AgentRun(id="x", project="p", prompt="q")
    lines = [
        {"type": "system", "subtype": "init", "model": "m", "mcp_servers": [{"name": "lightshow", "status": "failed"}]},
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "name": "mcp__lightshow__render_timeline", "input": {"start": 0, "end": 30}}]
            },
        },
        {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True, "content": "boom"}]}},
        {"type": "result", "subtype": "error_max_turns", "is_error": True, "num_turns": 50, "duration_ms": 100},
    ]
    for line in lines:
        parse_line(run, json.dumps(line))
    parse_line(run, "not json")
    kinds = [e["kind"] for e in run.events]
    assert kinds == ["info", "error", "tool", "warn"]
    assert run.events[2]["text"] == "Timeline-Bild gerendert" and run.events[2]["detail"] == "0-30 s"
    assert run.status == "error" and run.turns == 50


def test_prompt_mentions_task_and_brightness():
    song = {"id": "s1", "title": "Demo", "duration": 80.0}
    p = build_prompt("raum", song, "Ruhig und blau", "Blau", None)
    assert 'create_show an (name "Blau", song_id "s1")' in p and "0.03-0.15" in p and "Ruhig und blau" in p
    assert "hits" in p and "analyze_light" in p and "direkt" in p
    assert "show_id abc" in build_prompt("raum", song, "mehr Strobe", "x", "abc")


def test_run_through_api_with_fake_cli(tmp_path, monkeypatch):
    args_file = tmp_path / "args.json"
    monkeypatch.setenv("LSG_CLAUDE_CMD", f'"{sys.executable}" "{FAKE}"')
    monkeypatch.setenv("FAKE_CLAUDE_ARGS", str(args_file))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-be-passed")
    app = create_app(data_dir=tmp_path, audio="null", fps=50, frontend=tmp_path / "x")
    with TestClient(app) as c:
        slug = c.post("/api/projects", json={"name": "KI"}).json()["slug"]
        status = c.get("/api/ai/status").json()
        assert status["claude"]["installed"] and "fake" in status["claude"]["version"]
        run = c.post("/api/ai/run", json={"project": slug, "prompt": "Mach was Schönes"}).json()
        assert run["status"] == "running"
        assert c.post("/api/ai/run", json={"project": slug, "prompt": "nochmal"}).status_code == 409
        for _ in range(100):
            run = c.get("/api/ai/status").json()["run"]
            if run["status"] != "running":
                break
            time.sleep(0.1)
        assert run["status"] == "done", run
        assert run["result"] == "Die Show pulsiert im Refrain." and run["show_ids"] == ["abc123"]
        assert [e["text"] for e in run["events"] if e["kind"] == "tool"] == [
            "Projekt und Raum gelesen",
            "Show angelegt",
            "Clips hinzugefügt",
        ]
    args = json.loads(args_file.read_text())
    assert args[0] == "-p" and "--strict-mcp-config" in args and "--bare" not in args
    assert args[args.index("--allowedTools") + 1] == "mcp__lightshow"
    assert args[args.index("--permission-mode") + 1] == "dontAsk"
    cfg_path = args[args.index("--mcp-config") + 1]
    assert not Path(cfg_path).exists()  # temporary MCP config removed afterwards


def test_cancel(tmp_path, monkeypatch):
    monkeypatch.setenv("LSG_CLAUDE_CMD", f'"{sys.executable}" "{FAKE}"')
    monkeypatch.setenv("FAKE_CLAUDE_ARGS", str(tmp_path / "a.json"))
    monkeypatch.setenv("FAKE_CLAUDE_SLOW", "1")
    app = create_app(data_dir=tmp_path, audio="null", fps=50, frontend=tmp_path / "x")
    with TestClient(app) as c:
        slug = c.post("/api/projects", json={"name": "KI"}).json()["slug"]
        c.post("/api/ai/run", json={"project": slug, "prompt": "langsam bitte"})
        time.sleep(1.0)
        run = c.post("/api/ai/cancel").json()
        assert run["status"] == "cancelled"
        for _ in range(50):
            if c.get("/api/ai/status").json()["run"]["status"] != "running":
                break
            time.sleep(0.1)
        assert c.get("/api/ai/status").json()["run"]["status"] == "cancelled"


def test_missing_cli(tmp_path, monkeypatch):
    monkeypatch.setattr("lsg.ai_agent.claude_command", lambda: None)
    app = create_app(data_dir=tmp_path, audio="null", fps=50, frontend=tmp_path / "x")
    with TestClient(app) as c:
        slug = c.post("/api/projects", json={"name": "KI"}).json()["slug"]
        r = c.post("/api/ai/run", json={"project": slug, "prompt": "hallo du"})
        assert r.status_code == 424 and "nicht gefunden" in r.json()["detail"]


@pytest.fixture(autouse=True)
def _no_real_claude(monkeypatch):
    """Never start the real CLI from the test suite."""
    monkeypatch.delenv("CLAUDECODE", raising=False)
