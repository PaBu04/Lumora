import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from lsg.desktop import app_window_args

FAKE = Path(__file__).parent / "fake_browser.py"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def test_app_window_args(tmp_path):
    args = app_window_args(["edge.exe"], "http://127.0.0.1:8000", tmp_path / "profile")
    assert args[0] == "edge.exe" and "--app=http://127.0.0.1:8000" in args
    assert f"--user-data-dir={tmp_path / 'profile'}" in args


def test_closing_the_window_stops_the_server(tmp_path):
    port = free_port()
    args_file = tmp_path / "args.json"
    env = {
        **os.environ,
        "LSG_PORT": str(port),
        "LSG_DATA": str(tmp_path / "data"),
        "LSG_AUDIO": "null",
        "LSG_BROWSER": f'"{sys.executable}" "{FAKE}"',
        "FAKE_BROWSER_ARGS": str(args_file),
        "FAKE_BROWSER_SECONDS": "4",
    }
    proc = subprocess.Popen([sys.executable, "-m", "lsg.desktop"], env=env)
    try:
        for _ in range(100):
            if port_open(port):
                break
            time.sleep(0.1)
        assert port_open(port), "server did not come up"
        for _ in range(50):
            if args_file.exists():
                break
            time.sleep(0.1)
        args = json.loads(args_file.read_text())
        assert f"--app=http://127.0.0.1:{port}" in args
        assert proc.wait(timeout=20) == 0  # window "closed" -> launcher exits
        time.sleep(0.5)
        assert not port_open(port)
        assert (tmp_path / "data" / "desktop.log").is_file()
    finally:
        proc.kill()
