"""Stand-in for the `claude` CLI in tests: records its arguments and prints a stream-json session."""

import json
import os
import sys
import time

if "--version" in sys.argv:
    print("9.9.9 (Claude Code, fake)")
    sys.exit(0)
if sys.argv[1:] == ["update"]:
    print("Successfully updated from 9.9.9 to version 9.9.9")
    sys.exit(0)

with open(os.environ["FAKE_CLAUDE_ARGS"], "a", encoding="utf-8") as fh:  # one line per start
    fh.write(json.dumps(sys.argv[1:]) + "\n")


def emit(obj):
    print(json.dumps(obj), flush=True)
    time.sleep(0.05)


model = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "claude-default"
emit({"type": "system", "subtype": "init", "model": model, "mcp_servers": [{"name": "lightshow", "status": "connected"}]})
if "--model" in sys.argv and os.environ.get("FAKE_CLAUDE_OLD"):
    emit(
        {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "result": "API Error: 400 Claude Code 9.9.9 does not support this model; version 10.0 or newer is required. "
            "Run 'claude update', or update the Claude desktop app, then try again.",
        }
    )
    sys.exit(1)
emit({"type": "assistant", "message": {"content": [{"type": "text", "text": "Ich schaue mir zuerst den Raum an."}]}})
emit(
    {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": "t1", "name": "mcp__lightshow__get_overview", "input": {}}]},
    }
)
emit(
    {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "{}"}]}]},
    }
)
emit(
    {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "id": "t2", "name": "mcp__lightshow__create_show", "input": {"name": "Test"}}]
        },
    }
)
emit(
    {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content": '{"ok": true, "show_id": "abc123"}'}]},
    }
)
emit(
    {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": "t3",
                    "name": "mcp__lightshow__add_clips",
                    "input": {"layer": "Base", "clips": [{}, {}]},
                }
            ]
        },
    }
)
if os.environ.get("FAKE_CLAUDE_SLOW"):
    time.sleep(30)
emit(
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 4,
        "duration_ms": 1234,
        "result": "Die Show pulsiert im Refrain.",
    }
)
