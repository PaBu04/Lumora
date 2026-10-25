"""FastAPI application: REST API, WebSocket, the internal tool endpoint for Claude Code and the web UI."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.datastructures import Headers
from starlette.websockets import WebSocketClose

from lumora import config
from lumora.api import router, websocket_endpoint
from lumora.mcp_server import create_mcp
from lumora.state import AppState

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class LocalOnly:
    """Keeps other websites out of the app on localhost.

    Without CORS headers a browser does not let other sites read the answers, but it still sends their form
    posts and file uploads and opens WebSockets; DNS rebinding even makes such a site look like the same
    origin. So a request must name a local host (while the app listens on localhost), and a browser request
    must come from the app's own origin. Clients without an Origin header (Claude Code, scripts) pass.
    """

    def __init__(self, app, check_host: bool):
        self.app = app
        self.check_host = check_host

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = Headers(scope=scope)
            host = headers.get("host", "")
            origin = headers.get("origin")
            foreign_host = self.check_host and urlsplit(f"//{host}").hostname not in LOCAL_HOSTS
            if foreign_host or (origin is not None and urlsplit(origin).netloc != host):
                if scope["type"] == "websocket":
                    await WebSocketClose(code=1008)(scope, receive, send)
                else:
                    await PlainTextResponse("request from another website refused", status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app(
    data_dir: Path | None = None, audio: str | None = None, fps: float | None = None, frontend: Path | None = None
) -> FastAPI:
    from lumora import diagnostics

    diagnostics.install()  # last log lines for the diagnostics package
    st = AppState(data_dir or config.DATA_DIR, audio or config.AUDIO_BACKEND, fps or config.FPS)
    mcp = create_mcp(st)
    mcp_app = mcp.streamable_http_app(streamable_http_path="/mcp", host=config.HOST)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        st.loop = asyncio.get_running_loop()
        st.session.start()
        if st.active_project:
            try:
                await st.session.load_project(st.active_project)
            except Exception:
                logging.exception("could not load active project")
        st.resume_pending_analyses()
        if st.settings.get("remote_enabled") and st.settings.get("remote_key"):
            await st.remote.start()
        async with mcp.session_manager.run():
            yield
        await st.remote.stop()
        st.stop_analyses()
        await st.ai.shutdown()
        from lumora.render import shader_host

        shader_host.shutdown()
        await st.session.stop_loop()
        st.shutdown()

    app = FastAPI(title="Lumora", lifespan=lifespan)
    app.add_middleware(LocalOnly, check_host=config.HOST in LOCAL_HOSTS)
    app.state.lumora = st
    app.include_router(router)
    app.add_api_websocket_route("/ws", websocket_endpoint)
    # the MCP endpoint lives at /mcp next to the API
    app.router.routes.extend(mcp_app.routes)

    @app.exception_handler(ValidationError)
    async def validation_error(request: Request, exc: ValidationError):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(KeyError)
    async def key_error(request: Request, exc: KeyError):
        return JSONResponse({"detail": str(exc).strip("'\"")}, status_code=404)

    dist = Path(frontend or config.FRONTEND_DIST)
    if (dist / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            f = (dist / path).resolve()
            if path and f.is_file() and dist.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html")

    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    print(f"Lumora: http://{config.HOST}:{config.PORT}")
    uvicorn.run(create_app(), host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
