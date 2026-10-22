"""MCP server: lets an AI read the room, LEDs, viewer and music analysis and program shows."""

import asyncio
from typing import Any

import numpy as np
from mcp.server.mcpserver import Image, MCPServer
from pydantic import ValidationError

from lsg.audio.features import AudioFeatures
from lsg.geometry.led_table import build_led_table
from lsg.geometry.sampling import curve_length
from lsg.model.fixture import MatrixGeometry
from lsg.model.show import Clip, Layer, Show
from lsg.render.autoshow import starter_show
from lsg.render.colors import PALETTES
from lsg.render.effects import catalog
from lsg.render.engine import Renderer
from lsg.render.shaders import SHADER_API, ShaderError
from lsg.render.snapshot import render_timeline_image, render_top_image, render_viewer_image
from lsg.render.validate import validate_show
from lsg.state import AppState

INSTRUCTIONS = """\
Neopixel Light Show Generator: program music-synchronised LED light shows for a real room.

Recommended workflow:
1. get_overview - room, viewer, fixtures (LED strips), songs and shows in one call.
2. get_song_analysis - tempo, beats, bars, sections and loudness curves of the song.
3. list_effects / get_show_format - the effect library and the show JSON format.
4. create_show, then add_clips / update_clips / remove_clips (or update_show for a full rewrite).
5. validate_show, then render_timeline (whole passages) and render_snapshot (single moments) to
   check your work visually. preview starts playback in the app so the user can watch and listen.

Conventions: metres, z is up, floor at z = 0. Viewer-relative angles: azimuth 0 = straight ahead,
negative = left, positive = right; elevation positive = up. Times are seconds of the song.
Align clip boundaries with beats/bars/sections from the analysis so the show feels in time.
Write custom effects as Python/numpy shaders with write_shader when the library is not enough.
"""

SHOW_FORMAT = """\
Show JSON
{
  "id": "auto", "name": "My show", "song_id": "<song id>", "master": 1.0,
  "layers": [                         # composited bottom (first) to top (last)
    {"name": "Base", "opacity": 1.0, "enabled": true, "clips": [
      {"id": "optional", "start": 0.0, "end": 16.5,          # seconds, end exclusive
       "effect": "noise",                                    # effect id or "shader:<name>"
       "params": {"palette": "ocean", "brightness": 0.6},
       "target": {"tags": ["ceiling"]},                     # omit = all LEDs
       "blend": "normal",                                    # normal | add | max | multiply | subtract
       "opacity": 1.0, "fade_in": 1.0, "fade_out": 0.5}
    ]}
  ]
}

Target (which LEDs): {"fixtures": [ids], "tags": [tags], "where": [{"field": f, "min": a, "max": b}], "invert": false}
  fixtures/tags are OR-ed, where-ranges AND-ed on top. Fields: x, y, z, distance (metres),
  nx, ny, nz, u (0..1; n* = normalised in room bounds, u = along the strip), azimuth, elevation (degrees).

Parameter values can be animated (number params; keyframes also for colours and points):
  audio binding: {"audio": "low", "min": 0.1, "max": 1.0, "pow": 1.0}
     sources: rms, low, mid, high, onset, beat_phase, bar_phase, beat_decay, bar_decay, onset_decay, section_energy
  keyframes:     {"keys": [[0, "#ff0000"], [8, "#0000ff"]], "ease": "linear|smooth|step"}  (seconds from clip start)
  lfo:           {"lfo": "sine|triangle|saw|square", "beats": 2, "min": 0, "max": 1, "phase": 0}  (or "seconds": 3)

Colours: "#ff0080", "#f08", names (red, orange, amber, yellow, lime, green, mint, cyan, sky, blue, purple,
violet, magenta, pink, white, warmwhite, black), "hsv(200,1,1)" or [r, g, b] 0..255.
Palettes: a palette name or a list of colours.
Axes (for gradients, waves, chases...): x, y, z, u, azimuth (left->right as seen by the viewer),
elevation (bottom->top as seen), distance (near->far), radial (room centre outwards), angle (around the
room centre), fixture, or a vector [dx, dy, dz]. Prefix "-" to reverse, e.g. "-azimuth".
Tempo locking: most moving effects take "beats" (> 0 = one cycle per N beats) instead of "speed".
"""


def _err(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": str(exc)}


def create_mcp(st: AppState) -> MCPServer:
    mcp = MCPServer(name="neopixel-light-show-generator", instructions=INSTRUCTIONS, version="0.1.0")

    def project_and_table(project: str | None):
        slug = st.resolve_project(project)
        p = st.projects.load(slug)
        return slug, p, build_led_table(p)

    def features_for(show: Show) -> AudioFeatures:
        if not show.song_id:
            return AudioFeatures(None, show.duration)
        try:
            song = st.songs.get(show.song_id)
        except KeyError:
            return AudioFeatures(None, show.duration)
        return AudioFeatures(st.songs.analysis(show.song_id), song.duration)

    def fixture_summaries(p, table) -> list[dict[str, Any]]:
        out = []
        for f in p.fixtures:
            sl = table.fixture_slice(f.id)
            if sl.stop == sl.start:
                continue
            pos = table.pos[sl]
            az, el, dist = table.azimuth[sl], table.elevation[sl], table.distance[sl]
            length = None if isinstance(f.geometry, MatrixGeometry) else round(curve_length(f.geometry), 3)
            out.append({
                "id": f.id, "name": f.name, "type": f.geometry.type, "tags": f.tags,
                "led_type": f.led_type.value, "led_count": sl.stop - sl.start, "length_m": length,
                "first_led": np.round(pos[0], 2).tolist(), "last_led": np.round(pos[-1], 2).tolist(),
                "bbox_min": np.round(pos.min(axis=0), 2).tolist(), "bbox_max": np.round(pos.max(axis=0), 2).tolist(),
                "azimuth_range": [round(float(az.min()), 1), round(float(az.max()), 1)],
                "elevation_range": [round(float(el.min()), 1), round(float(el.max()), 1)],
                "distance_range": [round(float(dist.min()), 2), round(float(dist.max()), 2)],
                "azimuth_first_last": [round(float(az[0]), 1), round(float(az[-1]), 1)],
            })
        return out

    async def notify(slug: str, show_id: str) -> None:
        await st.show_changed(slug, show_id)

    def load_show(slug: str, show_id: str) -> Show:
        try:
            return st.show_store(slug).get(show_id)
        except KeyError:
            names = [f"{s.id} ({s.name})" for s in st.show_store(slug).list()]
            raise KeyError(f"unknown show {show_id!r}; shows: {names}")

    def issues_for(slug: str, p, table, show: Show) -> list[dict[str, Any]]:
        shaders, _ = st.show_store(slug).load_shaders()
        return validate_show(show, p, table, features_for(show), shaders)

    async def save_and_check(slug: str, show: Show) -> dict[str, Any]:
        _, p, table = project_and_table(slug)
        st.show_store(slug).save(show)
        issues = await asyncio.to_thread(issues_for, slug, p, table, show)
        await notify(slug, show.id)
        return {
            "ok": True, "show_id": show.id, "layers": [l.name for l in show.layers],
            "clips": sum(len(l.clips) for l in show.layers), "issues": issues,
        }

    # ---- reading ----

    @mcp.tool()
    def get_overview(project: str | None = None) -> dict[str, Any]:
        """Room, viewer, fixtures, songs and shows of the (active) project in one call. Start here."""
        slug, p, table = project_and_table(project)
        (x0, y0, _), (x1, y1, h) = p.room.bounds
        return {
            "project": slug,
            "projects": st.projects.list(),
            "room": {"floor_polygon": p.room.floor, "height": p.room.height,
                     "bounds": {"x": [x0, x1], "y": [y0, y1], "z": [0, h]}},
            "viewer": p.viewer.model_dump(),
            "led_count": table.count,
            "fixtures": fixture_summaries(p, table),
            "tags": sorted({t for f in p.fixtures for t in f.tags}),
            "songs": [{"id": s.id, "title": s.title, "artist": s.artist, "duration": s.duration, "analysis": s.status}
                      for s in st.songs.list()],
            "shows": [{"id": s.id, "name": s.name, "song_id": s.song_id} for s in st.show_store(slug).list()],
            "shaders": st.show_store(slug).shader_names(),
            "coordinates": "metres, z up, floor z=0; azimuth negative = left of viewer, elevation positive = up",
        }

    @mcp.tool()
    def get_led_positions(fixture_id: str, stride: int = 1, project: str | None = None) -> dict[str, Any]:
        """Per-LED data of one fixture in data order: position [x,y,z], azimuth, elevation, distance, u.
        Use stride > 1 to thin out long strips."""
        _, p, table = project_and_table(project)
        if fixture_id not in table.fixture_ids:
            return _err(KeyError(f"unknown fixture {fixture_id!r}; fixtures: {table.fixture_ids}"))
        sl = table.fixture_slice(fixture_id)
        idx = np.arange(sl.start, sl.stop)[:: max(1, stride)]
        return {
            "fixture_id": fixture_id, "count": sl.stop - sl.start, "stride": max(1, stride),
            "index": (idx - sl.start).tolist(),
            "pos": np.round(table.pos[idx], 3).tolist(),
            "azimuth": np.round(table.azimuth[idx], 1).tolist(),
            "elevation": np.round(table.elevation[idx], 1).tolist(),
            "distance": np.round(table.distance[idx], 2).tolist(),
            "u": np.round(table.u[idx], 3).tolist(),
        }

    @mcp.tool()
    def get_song_analysis(song_id: str, start: float = 0.0, end: float | None = None, resolution_hz: float = 4.0,
                          include_onsets: bool = False) -> dict[str, Any]:
        """Music analysis: bpm, beats, downbeats (bar starts), sections (intro/verse/chorus/bridge/break/outro with
        similarity labels and energy) and loudness curves (rms, low, mid, high, onset; 0..1) resampled to
        resolution_hz inside [start, end]. Request long songs in windows."""
        try:
            song = st.songs.get(song_id)
        except KeyError:
            return _err(KeyError(f"unknown song {song_id!r}"))
        a = st.songs.analysis(song_id)
        if a is None:
            return {"ok": False, "song": song.model_dump(), "error": f"analysis is {song.status}; try again shortly"}
        end = a.duration if end is None else min(end, a.duration)
        res = min(max(resolution_hz, 0.5), 20.0)
        times = np.arange(start, end, 1.0 / res)
        f = AudioFeatures(a)
        in_win = lambda xs: [x for x in xs if start <= x < end]
        out = {
            "song": {"id": song.id, "title": song.title, "artist": song.artist, "duration": a.duration},
            "bpm": a.bpm,
            "beat_period": round(60.0 / a.bpm, 4) if a.bpm else None,
            "window": [start, round(end, 3)],
            "sections": [s.model_dump() for s in a.sections],
            "beats": in_win(a.beats),
            "downbeats": in_win(a.downbeats),
            "curves": {
                "times": np.round(times, 3).tolist(),
                **{name: [round(f.level(name, float(t)), 2) for t in times] for name in ("rms", "low", "mid", "high", "onset")},
            },
        }
        if include_onsets:
            out["onsets"] = in_win(a.onsets)
        return out

    @mcp.tool()
    def list_effects() -> dict[str, Any]:
        """Effect library with parameter schemas, the named palettes and the parameter value syntax."""
        return {"effects": catalog(), "palettes": PALETTES, "format": SHOW_FORMAT}

    @mcp.tool()
    def get_show_format() -> str:
        """Documentation of the show JSON format: layers, clips, targets, blend modes, animated parameters."""
        return SHOW_FORMAT

    @mcp.tool()
    def list_shows(project: str | None = None) -> list[dict[str, Any]]:
        """Shows of the project."""
        slug = st.resolve_project(project)
        return [{"id": s.id, "name": s.name, "song_id": s.song_id, "description": s.description,
                 "layers": [l.name for l in s.layers], "clips": sum(len(l.clips) for l in s.layers)}
                for s in st.show_store(slug).list()]

    @mcp.tool()
    def get_show(show_id: str, project: str | None = None) -> dict[str, Any]:
        """Full JSON of a show."""
        slug = st.resolve_project(project)
        try:
            return load_show(slug, show_id).model_dump()
        except KeyError as exc:
            return _err(exc)

    # ---- writing ----

    @mcp.tool()
    async def create_show(name: str, song_id: str | None = None, template: str = "empty",
                          layers: list[dict] | None = None, description: str = "", project: str | None = None) -> dict[str, Any]:
        """Create a show for a song. template: 'empty' or 'starter' (rule-based show from the song structure).
        Optionally pass layers directly (same format as in get_show_format). Returns the show id and issues."""
        slug = st.resolve_project(project)
        analysis, duration = None, None
        if song_id:
            try:
                duration = st.songs.get(song_id).duration
            except KeyError:
                return _err(KeyError(f"unknown song {song_id!r}"))
            analysis = st.songs.analysis(song_id)
        try:
            if layers is not None:
                show = Show(name=name, song_id=song_id, description=description, layers=[Layer.model_validate(l) for l in layers])
            elif template == "starter":
                show = starter_show(name, song_id, analysis, duration)
            else:
                show = Show(name=name, song_id=song_id, description=description)
        except ValidationError as exc:
            return _err(exc)
        if description:
            show.description = description
        return await save_and_check(slug, show)

    @mcp.tool()
    async def update_show(show: dict, project: str | None = None) -> dict[str, Any]:
        """Replace a whole show (must contain its existing id). Returns validation issues."""
        slug = st.resolve_project(project)
        try:
            new = Show.model_validate(show)
            load_show(slug, new.id)
        except (ValidationError, KeyError) as exc:
            return _err(exc)
        return await save_and_check(slug, new)

    @mcp.tool()
    async def add_clips(show_id: str, layer: str, clips: list[dict], project: str | None = None) -> dict[str, Any]:
        """Append clips to the layer with this name (created on top if missing). Clip fields: start, end,
        effect, params, target, blend, opacity, fade_in, fade_out, optional id."""
        slug = st.resolve_project(project)
        try:
            show = load_show(slug, show_id)
            new_clips = [Clip.model_validate(c) for c in clips]
        except (ValidationError, KeyError) as exc:
            return _err(exc)
        target = next((l for l in show.layers if l.name == layer), None)
        if target is None:
            target = Layer(name=layer)
            show.layers.append(target)
        target.clips.extend(new_clips)
        result = await save_and_check(slug, show)
        result["added"] = [c.id for c in new_clips]
        return result

    @mcp.tool()
    async def update_clips(show_id: str, updates: list[dict], project: str | None = None) -> dict[str, Any]:
        """Change clips in place. Each update: {"id": clip_id, <fields to change>}. 'params' is merged
        key by key; use null as a param value to remove it."""
        slug = st.resolve_project(project)
        try:
            show = load_show(slug, show_id)
        except KeyError as exc:
            return _err(exc)
        by_id = {c.id: (layer, i) for layer in show.layers for i, c in enumerate(layer.clips)}
        for u in updates:
            cid = u.get("id")
            if cid not in by_id:
                return _err(KeyError(f"unknown clip {cid!r}"))
            layer, i = by_id[cid]
            data = layer.clips[i].model_dump()
            for k, v in u.items():
                if k == "params" and isinstance(v, dict):
                    for pk, pv in v.items():
                        if pv is None:
                            data["params"].pop(pk, None)
                        else:
                            data["params"][pk] = pv
                elif k != "id":
                    data[k] = v
            try:
                layer.clips[i] = Clip.model_validate(data)
            except ValidationError as exc:
                return _err(exc)
        return await save_and_check(slug, show)

    @mcp.tool()
    async def remove_clips(show_id: str, clip_ids: list[str], project: str | None = None) -> dict[str, Any]:
        """Delete clips by id."""
        slug = st.resolve_project(project)
        try:
            show = load_show(slug, show_id)
        except KeyError as exc:
            return _err(exc)
        ids = set(clip_ids)
        for layer in show.layers:
            layer.clips = [c for c in layer.clips if c.id not in ids]
        return await save_and_check(slug, show)

    @mcp.tool()
    async def delete_show(show_id: str, project: str | None = None) -> dict[str, Any]:
        """Delete a show."""
        slug = st.resolve_project(project)
        try:
            st.show_store(slug).delete(show_id)
        except KeyError as exc:
            return _err(exc)
        await notify(slug, show_id)
        return {"ok": True}

    @mcp.tool()
    async def validate(show_id: str, project: str | None = None) -> dict[str, Any]:
        """Check a show for errors (broken params, unknown targets, failing shaders) and warnings."""
        slug, p, table = project_and_table(project)
        try:
            show = load_show(slug, show_id)
        except KeyError as exc:
            return _err(exc)
        issues = await asyncio.to_thread(issues_for, slug, p, table, show)
        return {"ok": not any(i["severity"] == "error" for i in issues), "issues": issues}

    # ---- shaders ----

    @mcp.tool()
    def get_shader_api() -> str:
        """How to write a custom Python/numpy shader effect (used as effect 'shader:<name>')."""
        return SHADER_API

    @mcp.tool()
    async def write_shader(name: str, code: str, project: str | None = None) -> dict[str, Any]:
        """Create or replace a shader. It is checked and test-rendered on all LEDs before saving."""
        slug, p, table = project_and_table(project)
        store = st.show_store(slug)
        try:
            from lsg.render.shaders import Shader

            shader = Shader(name, code)
            probe = Show(layers=[Layer(clips=[Clip(id="probe", start=0, end=10, effect=f"shader:{name}")])])
            r = Renderer(p, table, probe, AudioFeatures(None, 10), {name: shader})
            for t in (0.0, 1.3, 4.7):
                r.render(t)
            if r.errors:
                return {"ok": False, "error": r.errors["probe"]}
            store.save_shader(name, code)
        except ShaderError as exc:
            return _err(exc)
        await st.shaders_changed(slug)
        return {"ok": True, "effect": f"shader:{name}", "render_ms": None}

    @mcp.tool()
    def get_shader(name: str, project: str | None = None) -> dict[str, Any]:
        """Source code of a shader."""
        slug = st.resolve_project(project)
        try:
            return {"name": name, "code": st.show_store(slug).shader_source(name)}
        except KeyError:
            return _err(KeyError(f"unknown shader {name!r}"))

    # ---- looking at results ----

    def renderer_for(slug: str, p, table, show: Show) -> Renderer:
        shaders, _ = st.show_store(slug).load_shaders()
        return Renderer(p, table, show, features_for(show), shaders)

    @mcp.tool()
    async def render_snapshot(show_id: str, t: float, view: str = "viewer", project: str | None = None) -> Any:
        """Image of the show at time t. view='viewer': what the audience sees from the viewer position;
        view='top': floor plan from above with fixture names."""
        slug, p, table = project_and_table(project)
        try:
            show = load_show(slug, show_id)
        except KeyError as exc:
            return _err(exc)

        def work():
            r = renderer_for(slug, p, table, show)
            frame = r.render(t)
            return render_top_image(p, table, frame) if view == "top" else render_viewer_image(p, table, frame)

        return Image(data=await asyncio.to_thread(work), format="png")

    @mcp.tool()
    async def render_timeline(show_id: str, start: float = 0.0, end: float = 30.0, project: str | None = None) -> Any:
        """Overview image of a time range: x = time, y = LEDs grouped by fixture, with section names and
        bar ticks on top. Best way to check rhythm, transitions and coverage."""
        slug, p, table = project_and_table(project)
        try:
            show = load_show(slug, show_id)
        except KeyError as exc:
            return _err(exc)
        if end <= start:
            return _err(ValueError("end must be after start"))

        def work():
            return render_timeline_image(renderer_for(slug, p, table, show), start, end, width=800)

        return Image(data=await asyncio.to_thread(work), format="png")

    @mcp.tool()
    async def preview(show_id: str, start: float = 0.0, play: bool = True, project: str | None = None) -> dict[str, Any]:
        """Load the show in the app (3D preview and, if live mode is on, the real LEDs) and start playback."""
        slug = st.resolve_project(project)
        try:
            await st.activate_project(slug)
            await st.session.load_show(slug, show_id)
        except KeyError as exc:
            return _err(exc)
        st.session.seek(start)
        if play:
            st.session.play()
        await st.session.broadcast_state()
        return st.session.state()

    @mcp.tool()
    async def playback(action: str, t: float | None = None) -> dict[str, Any]:
        """Control playback: action = play | pause | stop | seek (with t in seconds) | state."""
        s = st.session
        match action:
            case "play":
                s.play()
            case "pause":
                s.pause()
            case "stop":
                s.stop()
            case "seek":
                s.seek(t or 0.0)
            case "state":
                pass
            case _:
                return _err(ValueError("action must be play, pause, stop, seek or state"))
        await s.broadcast_state()
        return s.state()

    @mcp.resource("lsg://docs/show-format", name="show-format", mime_type="text/plain")
    def show_format_resource() -> str:
        return SHOW_FORMAT

    @mcp.resource("lsg://docs/shader-api", name="shader-api", mime_type="text/plain")
    def shader_api_resource() -> str:
        return SHADER_API

    return mcp
