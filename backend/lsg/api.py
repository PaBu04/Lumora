"""REST API and WebSocket used by the web UI."""

import asyncio
import re
import tempfile
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field, ValidationError

from lsg.audio.demo import make_demo_track
from lsg.audio.features import AudioFeatures
from lsg.geometry.led_table import build_led_table
from lsg.geometry.sampling import curve_length, fixture_led_count
from lsg.model.fixture import MatrixGeometry
from lsg.model.project import Project
from lsg.model.room import Room
from lsg.model.show import Show
from lsg.output import wled
from lsg.render.autoshow import starter_show
from lsg.render.colors import PALETTES
from lsg.render.effects import catalog
from lsg.render.engine import Renderer
from lsg.render.shaders import SHADER_API, ShaderError
from lsg.render.snapshot import render_timeline_image, render_top_image, render_viewer_image
from lsg.render.validate import validate_show
from lsg.state import AppState

router = APIRouter(prefix="/api")


def state(request: Request) -> AppState:
    return request.app.state.lsg


def _404(what: str):
    return HTTPException(404, f"{what} not found")


def _project(st: AppState, slug: str) -> Project:
    try:
        return st.projects.load(slug)
    except FileNotFoundError:
        raise _404(f"project {slug!r}")


def _show(st: AppState, slug: str, show_id: str) -> Show:
    try:
        return st.show_store(slug).get(show_id)
    except KeyError:
        raise _404(f"show {show_id!r}")


# projects


class NewProject(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    room: Room | None = None
    copy_from: str | None = None  # slug of a project to copy
    copy_shows: bool = True


@router.get("/projects")
def list_projects(request: Request):
    st = state(request)
    out = []
    for slug in st.projects.list():
        try:
            p = st.projects.load(slug)
            out.append({"slug": slug, "name": p.name, "fixtures": len(p.fixtures), "controllers": len(p.controllers)})
        except (ValidationError, OSError) as exc:
            out.append({"slug": slug, "name": slug, "error": str(exc)})
    return {"projects": out, "active": st.active_project}


@router.post("/projects")
async def create_project(request: Request, body: NewProject):
    st = state(request)
    if body.copy_from:
        _project(st, body.copy_from)
        slug = st.projects.copy(body.copy_from, body.name, body.copy_shows)
        await st.activate_project(slug)
        return {"slug": slug, "project": st.projects.load(slug)}
    room = body.room or Room(floor=[(0, 0), (5, 0), (5, 4), (0, 4)], height=2.5)
    project = Project(name=body.name, room=room)
    project.viewer.position = ((room.bounds[0][0] + room.bounds[1][0]) / 2, room.bounds[0][1] + 0.5, 1.6)
    project.viewer.yaw_deg = 90.0
    slug = st.projects.create(project)
    await st.activate_project(slug)
    return {"slug": slug, "project": project}


@router.get("/projects/{slug}")
def get_project(request: Request, slug: str):
    return _project(state(request), slug)


@router.put("/projects/{slug}")
async def put_project(request: Request, slug: str, project: Project):
    st = state(request)
    _project(st, slug)
    st.projects.save(slug, project)
    await st.project_changed(slug)
    return project


@router.delete("/projects/{slug}")
async def delete_project(request: Request, slug: str):
    import shutil

    st = state(request)
    _project(st, slug)
    if st.session.loaded and st.session.loaded.project_slug == slug:
        st.session.stop()
        st.session.loaded = None
    shutil.rmtree(st.projects.project_dir(slug))
    return {"ok": True}


@router.post("/projects/{slug}/activate")
async def activate(request: Request, slug: str):
    st = state(request)
    try:
        await st.activate_project(slug)
    except KeyError:
        raise _404(f"project {slug!r}")
    return st.session.state()


FLOORPLAN_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


@router.post("/projects/{slug}/floorplan")
async def upload_floorplan(request: Request, slug: str, file: UploadFile = File(...)):
    """Photo or blueprint to trace the room from; initially scaled to the width of the room."""
    from PIL import Image, UnidentifiedImageError

    from lsg.model.room import FloorplanImage

    st = state(request)
    project = _project(st, slug)
    ext = Path(file.filename or "plan.png").suffix.lower()
    if ext not in FLOORPLAN_TYPES:
        raise HTTPException(422, f"unsupported image type {ext!r}")
    data = await file.read()
    if len(data) > 30 * 1024 * 1024:
        raise HTTPException(413, "image larger than 30 MB")
    try:
        import io

        with Image.open(io.BytesIO(data)) as img:
            w, h = img.size
    except (UnidentifiedImageError, OSError):
        raise HTTPException(422, "not a readable image")
    pdir = st.projects.project_dir(slug)
    for old in pdir.glob("floorplan.*"):
        old.unlink()
    (pdir / f"floorplan{ext}").write_bytes(data)
    (x0, y0, _), (x1, _, _) = project.room.bounds
    project.floorplan = FloorplanImage(filename=f"floorplan{ext}", px_width=w, px_height=h, x=x0, y=y0, width_m=max(1.0, x1 - x0))
    st.projects.save(slug, project)
    await st.project_changed(slug)
    return project


@router.get("/projects/{slug}/floorplan")
def get_floorplan(request: Request, slug: str):
    st = state(request)
    project = _project(st, slug)
    if not project.floorplan:
        raise _404("floor plan image")
    path = st.projects.project_dir(slug) / project.floorplan.filename
    if not path.is_file():
        raise _404("floor plan image")
    return FileResponse(path)


@router.delete("/projects/{slug}/floorplan")
async def delete_floorplan(request: Request, slug: str):
    st = state(request)
    project = _project(st, slug)
    for old in st.projects.project_dir(slug).glob("floorplan.*"):
        old.unlink()
    project.floorplan = None
    st.projects.save(slug, project)
    await st.project_changed(slug)
    return project


@router.get("/projects/{slug}/leds")
def project_leds(request: Request, slug: str):
    """LED positions for the 3D view (positions flattened x,y,z...)."""
    project = _project(state(request), slug)
    table = build_led_table(project)
    fixtures = []
    for f in project.fixtures:
        sl = table.fixture_slice(f.id)
        length = 0.0 if isinstance(f.geometry, MatrixGeometry) else curve_length(f.geometry)
        fixtures.append({"id": f.id, "start": sl.start, "count": sl.stop - sl.start, "length": round(length, 3)})
    return {
        "count": table.count,
        "positions": np.round(table.pos, 4).ravel().tolist(),
        "fixtures": fixtures,
    }


@router.post("/fixtures/preview")
def fixture_preview(fixture: dict = Body(...)):
    """LED count/length of a fixture while it is being edited."""
    from lsg.model.fixture import Fixture

    try:
        f = Fixture.model_validate(fixture)
    except ValidationError as exc:
        raise HTTPException(422, str(exc))
    length = 0.0 if isinstance(f.geometry, MatrixGeometry) else curve_length(f.geometry)
    return {"count": fixture_led_count(f), "length": round(length, 3)}


# shows


class NewShow(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    song_id: str | None = None
    template: str = "starter"  # starter | empty


def _features(st: AppState, show: Show) -> AudioFeatures:
    if not show.song_id:
        return AudioFeatures(None, show.duration)
    try:
        song = st.songs.get(show.song_id)
    except KeyError:
        return AudioFeatures(None, show.duration)
    return AudioFeatures(st.songs.analysis(show.song_id), song.duration)


@router.get("/projects/{slug}/shows")
def list_shows(request: Request, slug: str):
    st = state(request)
    _project(st, slug)
    return [
        {
            "id": s.id,
            "name": s.name,
            "song_id": s.song_id,
            "description": s.description,
            "clips": sum(len(l.clips) for l in s.layers),
            "layers": len(s.layers),
        }
        for s in st.show_store(slug).list()
    ]


class ShowOrder(BaseModel):
    ids: list[str]


@router.put("/projects/{slug}/shows/order")
async def order_shows(request: Request, slug: str, body: ShowOrder):
    """Sort the show list (drag and drop in the UI)."""
    st = state(request)
    _project(st, slug)
    st.show_store(slug).set_order(body.ids)
    return list_shows(request, slug)


@router.post("/projects/{slug}/shows")
async def create_show(request: Request, slug: str, body: NewShow):
    st = state(request)
    project = _project(st, slug)
    analysis, duration = None, None
    if body.song_id:
        try:
            duration = st.songs.get(body.song_id).duration
        except KeyError:
            raise _404(f"song {body.song_id!r}")
        analysis = st.songs.analysis(body.song_id)
    if body.template == "starter":
        show = starter_show(body.name, body.song_id, analysis, duration, project, build_led_table(project))
    else:
        show = Show(name=body.name, song_id=body.song_id)
    st.show_store(slug).save(show, "system")
    return show


@router.get("/projects/{slug}/shows/{show_id}")
def get_show(request: Request, slug: str, show_id: str):
    return _show(state(request), slug, show_id)


@router.put("/projects/{slug}/shows/{show_id}")
async def put_show(request: Request, slug: str, show_id: str, show: Show):
    st = state(request)
    _show(st, slug, show_id)
    if show.id != show_id:
        raise HTTPException(422, "show id in body does not match the URL")
    st.show_store(slug).save(show)
    await st.show_changed(slug, show_id)
    return show


@router.delete("/projects/{slug}/shows/{show_id}")
async def delete_show(request: Request, slug: str, show_id: str):
    st = state(request)
    try:
        st.show_store(slug).delete(show_id)
    except KeyError:
        raise _404(f"show {show_id!r}")
    await st.show_changed(slug, show_id)
    return {"ok": True}


@router.get("/projects/{slug}/shows/{show_id}/versions")
def show_versions(request: Request, slug: str, show_id: str):
    st = state(request)
    show = _show(st, slug, show_id)
    store = st.show_store(slug)
    if not store.history(show_id).list():  # shows from before the history existed: seed a baseline
        store.save(show, "system")
    return store.history(show_id).list()


@router.get("/projects/{slug}/shows/{show_id}/versions/{version_id}")
def show_version(request: Request, slug: str, show_id: str, version_id: str):
    try:
        return Show.model_validate_json(state(request).show_store(slug).history(show_id).get(version_id))
    except KeyError:
        raise _404(f"version {version_id!r}")


@router.post("/projects/{slug}/shows/{show_id}/versions/{version_id}/restore")
async def restore_show_version(request: Request, slug: str, show_id: str, version_id: str):
    st = state(request)
    try:
        show = st.show_store(slug).restore(show_id, version_id)
    except KeyError:
        raise _404(f"version {version_id!r}")
    await st.show_changed(slug, show_id)
    return show


@router.get("/projects/{slug}/versions")
def project_versions(request: Request, slug: str):
    st = state(request)
    project = _project(st, slug)
    if not st.projects.history(slug).list():
        st.projects.save(slug, project, "system")
    return st.projects.history(slug).list()


@router.post("/projects/{slug}/versions/{version_id}/restore")
async def restore_project_version(request: Request, slug: str, version_id: str):
    st = state(request)
    _project(st, slug)
    try:
        project = st.projects.restore(slug, version_id)
    except KeyError:
        raise _404(f"version {version_id!r}")
    await st.project_changed(slug)
    return project


# looks


class NewLook(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = ""
    show_id: str
    clip_ids: list[str] = Field(min_length=1)


class InstantiateLook(BaseModel):
    show_id: str
    at: float = Field(ge=0)


@router.get("/projects/{slug}/looks")
def list_looks(request: Request, slug: str):
    from lsg.render.looks import BUILTIN_LOOKS

    st = state(request)
    _project(st, slug)
    return [*BUILTIN_LOOKS, *st.show_store(slug).looks()]


@router.post("/projects/{slug}/looks")
def create_look(request: Request, slug: str, body: NewLook):
    from lsg.render.looks import look_from_clips

    st = state(request)
    show = _show(st, slug, body.show_id)
    feats = _features(st, show)
    try:
        look = look_from_clips(body.name, show, set(body.clip_ids), feats.beat_position, body.description)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    st.show_store(slug).save_look(look)
    return look


@router.delete("/projects/{slug}/looks/{look_id}")
def delete_look(request: Request, slug: str, look_id: str):
    try:
        state(request).show_store(slug).delete_look(look_id)
    except KeyError:
        raise _404(f"look {look_id!r}")
    return {"ok": True}


@router.post("/projects/{slug}/looks/{look_id}/instantiate")
def instantiate_look(request: Request, slug: str, look_id: str, body: InstantiateLook):
    """Clips of a look converted to seconds for a position in a show (the UI inserts them itself)."""
    from lsg.render.looks import BUILTIN_LOOKS, apply_look

    st = state(request)
    look = next((x for x in [*BUILTIN_LOOKS, *st.show_store(slug).looks()] if x.id == look_id), None)
    if look is None:
        raise _404(f"look {look_id!r}")
    show = _show(st, slug, body.show_id)
    feats = _features(st, show)
    b0 = feats.beat_position(body.at)
    empty = Show(id=show.id, name=show.name, layers=[])
    placed, _ = apply_look(empty, look, body.at, 0, lambda b: feats.time_at_beat(b0 + b))
    return [{"layer": li, "clip": c} for li, layer in enumerate(placed.layers) for c in layer.clips]


@router.post("/projects/{slug}/shows/{show_id}/validate")
def validate(request: Request, slug: str, show_id: str):
    st = state(request)
    project = _project(st, slug)
    show = _show(st, slug, show_id)
    shaders, _ = st.show_store(slug).load_shaders()
    return validate_show(show, project, build_led_table(project), _features(st, show), shaders)


def _renderer(st: AppState, slug: str, show_id: str) -> Renderer:
    project = _project(st, slug)
    show = _show(st, slug, show_id)
    shaders, _ = st.show_store(slug).load_shaders()
    return Renderer(project, build_led_table(project), show, _features(st, show), shaders)


@router.get("/projects/{slug}/shows/{show_id}/power")
async def show_power(request: Request, slug: str, show_id: str, fps: float = Query(2.0, ge=0.5, le=10)):
    """Estimated current per controller over the show (before limiting)."""
    from lsg.output.pipeline import OutputPipeline
    from lsg.output.power import analyse_power

    st = state(request)
    r = _renderer(st, slug, show_id)
    return await asyncio.to_thread(analyse_power, r, OutputPipeline(r.project, r.table), fps, st.session.output.brightness)


@router.get("/projects/{slug}/shows/{show_id}/export")
async def export_show_package(request: Request, slug: str, show_id: str, fps: int = Query(40, ge=10, le=60), audio: bool = True):
    """Zip with FSEQ v2 sequence (xLights / Falcon Player), audio and channel map."""
    import tempfile

    from lsg.output.export import export_show

    st = state(request)
    r = _renderer(st, slug, show_id)
    song_path = None
    if audio and r.show.song_id:
        try:
            song_path = st.songs.audio_path(r.show.song_id)
        except KeyError:
            song_path = None
    out_dir = Path(tempfile.mkdtemp(prefix="lsg-export-"))
    out = out_dir / f"{re.sub(r'[^A-Za-z0-9._-]+', '_', r.show.name) or 'show'}.zip"
    try:
        await asyncio.to_thread(export_show, r, out, fps, st.session.output.brightness, song_path)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return FileResponse(out, media_type="application/zip", filename=out.name)


@router.get("/projects/{slug}/shows/{show_id}/snapshot.png")
def snapshot(request: Request, slug: str, show_id: str, t: float = 0.0, view: str = "viewer"):
    r = _renderer(state(request), slug, show_id)
    frame = r.render(t)
    png = render_top_image(r.project, r.table, frame) if view == "top" else render_viewer_image(r.project, r.table, frame)
    return Response(png, media_type="image/png")


@router.get("/projects/{slug}/shows/{show_id}/timeline.png")
def timeline(request: Request, slug: str, show_id: str, start: float = 0.0, end: float = 30.0, width: int = Query(800, le=2000)):
    r = _renderer(state(request), slug, show_id)
    if end <= start:
        raise HTTPException(422, "end must be after start")
    return Response(render_timeline_image(r, start, end, width), media_type="image/png")


# shaders


@router.get("/projects/{slug}/shaders")
def list_shaders(request: Request, slug: str):
    st = state(request)
    _project(st, slug)
    shaders, errors = st.show_store(slug).load_shaders()
    return {"shaders": sorted(set(shaders) | set(errors)), "errors": errors, "api": SHADER_API}


@router.get("/projects/{slug}/shaders/{name}", response_class=PlainTextResponse)
def get_shader(request: Request, slug: str, name: str):
    try:
        return state(request).show_store(slug).shader_source(name)
    except KeyError:
        raise _404(f"shader {name!r}")


@router.put("/projects/{slug}/shaders/{name}")
async def put_shader(request: Request, slug: str, name: str):
    st = state(request)
    _project(st, slug)
    source = (await request.body()).decode("utf-8")
    try:
        st.show_store(slug).save_shader(name, source)
    except (ShaderError, KeyError) as exc:
        raise HTTPException(422, str(exc))
    await st.shaders_changed(slug)
    return {"ok": True}


@router.delete("/projects/{slug}/shaders/{name}")
async def delete_shader(request: Request, slug: str, name: str):
    st = state(request)
    try:
        st.show_store(slug).delete_shader(name)
    except KeyError:
        raise _404(f"shader {name!r}")
    await st.shaders_changed(slug)
    return {"ok": True}


# songs


@router.get("/songs")
def list_songs(request: Request):
    return state(request).songs.list()


@router.post("/songs")
async def upload_song(
    request: Request, file: UploadFile = File(...), title: str | None = Form(None), artist: str | None = Form(None)
):
    st = state(request)
    try:
        song = await asyncio.to_thread(st.songs.add, file.file, file.filename or "upload.mp3", title, artist)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    st.analyse_song(song.id)
    await st.session.broadcast_event({"kind": "song_changed", "song": song.id, "status": song.status})
    return song


@router.post("/songs/demo")
async def demo_song(request: Request, bpm: float = 124.0):
    st = state(request)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"LSG - Demo {bpm:.0f} BPM.wav"
        await asyncio.to_thread(make_demo_track, path, bpm)
        song = await asyncio.to_thread(st.songs.add_file, path)
    st.analyse_song(song.id)
    return song


@router.get("/songs/{song_id}")
def get_song(request: Request, song_id: str):
    try:
        return state(request).songs.get(song_id)
    except KeyError:
        raise _404(f"song {song_id!r}")


class SongPatch(BaseModel):
    title: str | None = None
    artist: str | None = None


@router.patch("/songs/{song_id}")
async def patch_song(request: Request, song_id: str, body: SongPatch):
    try:
        return state(request).songs.update(song_id, body.title, body.artist)
    except KeyError:
        raise _404(f"song {song_id!r}")


@router.delete("/songs/{song_id}")
async def delete_song(request: Request, song_id: str):
    st = state(request)
    lo = st.session.loaded
    if lo and lo.show and lo.show.song_id == song_id:
        await st.session.load_show(lo.project_slug, None)
    try:
        st.songs.delete(song_id)
    except KeyError:
        raise _404(f"song {song_id!r}")
    await st.session.broadcast_event({"kind": "song_changed", "song": song_id, "status": "deleted"})
    return {"ok": True}


@router.post("/songs/{song_id}/analyse")
def reanalyse(request: Request, song_id: str, keep_tempo: bool = True):
    """keep_tempo: a hand-corrected tempo stays; false = detect the beats again."""
    st = state(request)
    try:
        st.songs.get(song_id)
    except KeyError:
        raise _404(f"song {song_id!r}")
    st.analyse_song(song_id, keep_tempo)
    return {"ok": True}


class TempoBody(BaseModel):
    factor: float | None = None  # 2 or 0.5: octave correction of the detected beats
    bpm: float | None = None  # exact tempo: even beat grid


@router.post("/songs/{song_id}/tempo")
async def song_tempo(request: Request, song_id: str, body: TempoBody):
    """Manual tempo correction: octave (factor 2 or 0.5) or an exact BPM value."""
    st = state(request)
    try:
        st.songs.get(song_id)
        if body.bpm is not None:
            analysis = st.songs.set_bpm(song_id, body.bpm)
        elif body.factor is not None:
            analysis = st.songs.scale_tempo(song_id, body.factor)
        else:
            raise ValueError("factor or bpm required")
    except KeyError:
        raise _404(f"song {song_id!r}")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    lo = st.session.loaded
    if lo and lo.show and lo.show.song_id == song_id:
        await st.session.reload(lo.project_slug, lo.show.id)
    await st.session.broadcast_event({"kind": "song_changed", "song": song_id, "status": "done"})
    return {"bpm": analysis.bpm, "beats": len(analysis.beats)}


@router.get("/songs/{song_id}/analysis")
def song_analysis(request: Request, song_id: str):
    a = state(request).songs.analysis(song_id)
    if a is None:
        raise _404("analysis")
    return a


@router.get("/songs/{song_id}/audio")
def song_audio(request: Request, song_id: str):
    try:
        return FileResponse(state(request).songs.audio_path(song_id))
    except KeyError:
        raise _404(f"song {song_id!r}")


# AI generation through the local Claude Code CLI (subscription, no API key)


class AiRunBody(BaseModel):
    project: str
    prompt: str = Field(min_length=3, max_length=4000)
    song_id: str | None = None
    show_name: str = "KI-Show"
    show_id: str | None = None
    model: str | None = None  # default: the app setting ai_model


@router.get("/ai/status")
async def ai_status(request: Request):
    from lsg.ai_agent import claude_status

    st = state(request)
    from lsg.ai_agent import AI_MODELS

    return {
        "claude": await claude_status(),
        "run": st.ai.current.to_dict() if st.ai.current else None,
        "models": AI_MODELS,
        "model": st.settings["ai_model"],
    }


@router.post("/ai/update")
async def ai_update(request: Request):
    """Update the Claude Code CLI (`claude update`), e.g. when a newer model needs a newer version."""
    from lsg.ai_agent import update_claude

    st = state(request)
    if st.ai.busy:
        raise HTTPException(409, "Es läuft gerade eine KI-Generierung")
    try:
        return await update_claude()
    except FileNotFoundError as exc:
        raise HTTPException(424, str(exc))


@router.post("/ai/run")
async def ai_run(request: Request, body: AiRunBody):
    st = state(request)
    _project(st, body.project)
    song = None
    if body.song_id:
        try:
            song = st.songs.get(body.song_id).model_dump()
        except KeyError:
            raise _404(f"song {body.song_id!r}")
    try:
        await st.activate_project(body.project)
        model = body.model or st.settings["ai_model"]
        if body.model and body.model != st.settings["ai_model"]:
            st.settings["ai_model"] = body.model
            st.save_settings()
        run = await st.ai.start(body.project, song, body.prompt, body.show_name, body.show_id, model)
    except FileNotFoundError as exc:
        raise HTTPException(424, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return run.to_dict()


@router.post("/ai/cancel")
async def ai_cancel(request: Request):
    st = state(request)
    await st.ai.cancel()
    return st.ai.current.to_dict() if st.ai.current else None


# settings


class SettingsBody(BaseModel):
    beat_tracker: str | None = None
    ai_model: str | None = None
    shader_isolation: bool | None = None


@router.get("/settings")
def get_settings(request: Request):
    from lsg.audio import ml_beats

    st = state(request)
    return {**st.settings, "beat_this": ml_beats.status()}


@router.put("/settings")
async def put_settings(request: Request, body: SettingsBody):
    st = state(request)
    if body.beat_tracker is not None:
        if body.beat_tracker not in ("librosa", "beat_this", "auto"):
            raise HTTPException(422, "beat_tracker must be librosa, beat_this or auto")
        st.settings["beat_tracker"] = body.beat_tracker
    if body.ai_model is not None:
        from lsg.ai_agent import AI_MODELS

        if body.ai_model not in AI_MODELS:
            raise HTTPException(422, f"ai_model must be one of {sorted(AI_MODELS)}")
        st.settings["ai_model"] = body.ai_model
    if body.shader_isolation is not None:
        from lsg.render import shader_host

        st.settings["shader_isolation"] = shader_host.ENABLED = body.shader_isolation
        if st.active_project:
            await st.shaders_changed(st.active_project)
    st.save_settings()
    return get_settings(request)


# effects


@router.get("/effects")
def effects():
    return {"effects": catalog(), "palettes": PALETTES, "shader_api": SHADER_API}


# playback


class LoadBody(BaseModel):
    project: str
    show: str | None = None


class SeekBody(BaseModel):
    t: float = Field(ge=0)


class ModeBody(BaseModel):
    mode: str


class OutputBody(BaseModel):
    brightness: float | None = Field(default=None, ge=0.0, le=1.0)
    audio_latency_ms: float | None = Field(default=None, ge=-1000, le=2000)


class TestBody(BaseModel):
    enabled: bool
    fixture_id: str | None = None
    kind: str = "identify"
    params: dict = Field(default_factory=dict)


@router.get("/playback")
def playback_state(request: Request):
    return state(request).session.state()


@router.post("/playback/load")
async def playback_load(request: Request, body: LoadBody):
    st = state(request)
    try:
        await st.activate_project(body.project)
        await st.session.load_show(body.project, body.show)
    except KeyError as exc:
        raise _404(str(exc))
    return st.session.state()


@router.post("/playback/play")
async def playback_play(request: Request):
    s = state(request).session
    s.play()
    await s.broadcast_state()
    return s.state()


@router.post("/playback/pause")
async def playback_pause(request: Request):
    s = state(request).session
    s.pause()
    await s.broadcast_state()
    return s.state()


@router.post("/playback/stop")
async def playback_stop(request: Request):
    s = state(request).session
    s.stop()
    await s.broadcast_state()
    return s.state()


@router.post("/playback/seek")
async def playback_seek(request: Request, body: SeekBody):
    s = state(request).session
    s.seek(body.t)
    return s.state()


@router.post("/playback/mode")
async def playback_mode(request: Request, body: ModeBody):
    s = state(request).session
    try:
        s.set_mode(body.mode)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return s.state()


@router.post("/playback/output")
async def playback_output(request: Request, body: OutputBody):
    s = state(request).session
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(s.output, k, v)
    state(request).save_settings()
    s._dirty = True
    return s.state()


class SyncBody(BaseModel):
    enabled: bool
    bpm: float = Field(default=100.0, ge=40, le=200)


@router.post("/playback/sync")
async def playback_sync(request: Request, body: SyncBody):
    """Click track + LED flashes on every beat to tune audio and controller latencies."""
    s = state(request).session
    try:
        if body.enabled:
            await s.start_sync(body.bpm)
        else:
            await s.stop_sync()
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return s.state()


class LiveBody(BaseModel):
    enabled: bool
    show_id: str | None = None
    device: int | str | None = None  # sound card index or "desktop[:speaker]"
    file_song_id: str | None = None  # feed a song file instead of the microphone (demo / tests)


@router.get("/live/devices")
def live_devices():
    from lsg.audio.live import input_devices

    return input_devices()


@router.post("/playback/live-input")
async def playback_live_input(request: Request, body: LiveBody):
    """Live input mode: the show reacts to the microphone in real time (no pre-analysis)."""
    st = state(request)
    s = st.session
    try:
        if body.enabled:
            file = st.songs.audio_path(body.file_song_id) if body.file_song_id else None
            await s.start_live_input(body.show_id, body.device, file)
        else:
            await s.stop_live_input()
    except KeyError as exc:
        raise _404(str(exc))
    except Exception as exc:  # no input device, PortAudio errors ...
        raise HTTPException(422, f"Live-Eingang nicht möglich: {exc}")
    return s.state()


@router.post("/playback/test")
async def playback_test(request: Request, body: TestBody):
    s = state(request).session
    if not s.loaded:
        raise HTTPException(409, "no project loaded")
    try:
        s.set_test(body.fixture_id, body.enabled, body.kind, body.params)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return s.state()


class SpeedTestBody(BaseModel):
    controller_id: str


@router.post("/playback/speedtest")
async def playback_speedtest(request: Request, body: SpeedTestBody):
    """Measure the frames per second a controller really shows (sends a test pattern for ~6 s)."""
    s = state(request).session
    try:
        return await s.speed_test(body.controller_id)
    except KeyError as exc:
        raise _404(str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:  # WLED unreachable
        raise HTTPException(502, f"Messung fehlgeschlagen: {exc}")


# devices


@router.get("/devices/discover")
async def discover(seconds: float = Query(3.0, ge=0.5, le=15)):
    return await wled.discover(seconds)


@router.get("/devices/info")
async def device_info(host: str):
    try:
        return await wled.fetch_info(host)
    except Exception as exc:
        raise HTTPException(502, f"cannot reach WLED at {host}: {exc}")


# websocket


async def websocket_endpoint(ws: WebSocket):
    st: AppState = ws.app.state.lsg
    await ws.accept()
    st.session.clients.add(ws)
    try:
        import json

        await ws.send_text(json.dumps(st.session.state()))
        st.session._dirty = True
        while True:
            await ws.receive_text()  # clients only listen; keep the socket open
    except WebSocketDisconnect:
        pass
    finally:
        st.session.clients.discard(ws)
