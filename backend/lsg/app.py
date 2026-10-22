"""FastAPI application: REST API, WebSocket, MCP endpoint and the built web UI."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from lsg import config
from lsg.api import router, websocket_endpoint
from lsg.mcp_server import create_mcp
from lsg.state import AppState


def create_app(
    data_dir: Path | None = None, audio: str | None = None, fps: float | None = None, frontend: Path | None = None
) -> FastAPI:
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
        async with mcp.session_manager.run():
            yield
        await st.ai.shutdown()
        await st.session.stop_loop()
        st.shutdown()

    app = FastAPI(title="Neopixel Light Show Generator", lifespan=lifespan)
    app.state.lsg = st
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
    print(f"Light Show Generator: http://{config.HOST}:{config.PORT}  (MCP: http://{config.HOST}:{config.PORT}/mcp)")
    uvicorn.run(create_app(), host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
