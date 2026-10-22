"""Desktop launcher: runs the server and opens the UI as an app window (Edge / Chrome app mode).

The window uses its own browser profile, so the launched browser process belongs to this
window alone: when the window is closed the server stops too. Without a Chromium based
browser the default browser is opened and the server runs until it is stopped.
"""

import logging
import os
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from lsg import config

log = logging.getLogger("lsg.desktop")

CANDIDATES = [
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_browser() -> list[str] | None:
    """Command of a Chromium based browser (LSG_BROWSER may be a full command line)."""
    override = os.environ.get("LSG_BROWSER")
    if override:
        return [t.strip('"') for t in shlex.split(override, posix=os.name != "nt")]
    for c in CANDIDATES:
        path = os.path.expandvars(c)
        if Path(path).is_file():
            return [path]
    for name in ("msedge", "chrome", "chromium", "google-chrome"):
        found = shutil.which(name)
        if found:
            return [found]
    return None


def app_window_args(browser: list[str], url: str, profile: Path) -> list[str]:
    return [
        *browser,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--window-size=1600,950",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def port_in_use(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if port_in_use(host, port):
            return True
        time.sleep(0.1)
    return False


def main() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_file = config.DATA_DIR / "desktop.log"
    if sys.stdout is None or sys.stderr is None:
        # started without a console (gui-script): libraries like uvicorn need real streams
        stream = open(log_file, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives as long as the process
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
    logging.basicConfig(filename=log_file, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        _run()
    except Exception:
        log.exception("desktop launcher failed")
        raise


def _run() -> None:
    url = f"http://{config.HOST}:{config.PORT}"
    server = None
    if port_in_use(config.HOST, config.PORT):
        log.info("app already running on %s, only opening a window", url)
    else:
        import uvicorn

        from lsg.app import create_app

        server = uvicorn.Server(uvicorn.Config(create_app(), host=config.HOST, port=config.PORT, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        if not wait_for_port(config.HOST, config.PORT):
            log.error("server did not start")
            sys.exit(1)

    browser = find_browser()
    if browser:
        proc = subprocess.Popen(app_window_args(browser, url, config.DATA_DIR / "browser-profile"))
        log.info("app window opened (%s, pid %s)", browser, proc.pid)
        proc.wait()  # the window was closed
        log.info("window closed")
    else:
        webbrowser.open(url)
        log.info("no Chromium browser found, opened the default browser; stop with Ctrl+C")
        try:
            while server is not None:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    if server is not None:
        server.should_exit = True
        time.sleep(1.5)


if __name__ == "__main__":
    main()
