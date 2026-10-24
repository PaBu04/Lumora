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
from lsg.output.curve import pwm_of_level
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

Workflow:
1. get_overview - room, viewer, fixtures (LED strips: length, LED count, how much the viewer sees them
   directly), songs and shows in one call.
2. get_song_analysis - tempo, bars, sections, loudness curves and the INSTRUMENTS: per section which
   instruments play (drums, bass, vocals, other = keys / synths / guitars), sung phrases, drops, build-ups,
   drum fills, crashes. get_song_events - the individual notes and hits of an instrument in a time window.
   You may also use what you know about the song (title / artist): its mood, hook, famous moments.
3. list_effects / get_show_format - the effect library and the show JSON format.
4. create_show (template "empty"), then add_clips / update_clips / remove_clips.
5. validate (errors, brightness, monotony), analyze_light (room light, quiet passages, contrast per
   section), render_timeline / render_snapshot to look at the result; fix and repeat. preview plays it.

HOW A GOOD SHOW LOOKS - follow these rules:
- FOLLOW THE SOUND, NOT THE GRID. Music is more than 4/4 beats: light what the instruments actually do.
  Every effect with a trigger can follow an instrument track: kick, snare, hihat, crash (drum hits with
  velocity - fills and rolls come out as played, faster in transitions), bass, vocal, keys (every note of
  keys / synths / guitars, polyphonic: a chord is several notes at once), lead (their melody = top voice),
  all notes with pitch and length, phrase (sung passages), fill, build, drop, no_drums, chord (chord
  changes, pitch = root), stab (chords struck short), pad (held chords), arp (arpeggios). "hits" on kick / snare for the
  beat, "notes" for melodies and bass lines (position = pitch, stays lit while the note sounds),
  "pulse" with sustain on phrase for a glow while someone sings. Loud hits are brighter (velocity).
  Give the instrument that carries a passage the most visible strip in it (e.g. vocals in the verse,
  the lead synth in the drop, the drums in a fill).
- PLAN THE ARC OF THE WHOLE SONG. Sections come with the song form: name (intro, verse, prechorus, chorus,
  break, build, drop, bridge, outro), label (same letter = same music), repeat (2 = second time), bars and
  intensity 1-5 relative to the song; one section is the peak. Scale the light with intensity and keep the
  brightest, widest look for the peak - do not spend everything on the first chorus. Give each label its
  own theme (colours, effects, which strip leads) and repeat it when the label comes back, a bit bigger on
  the repeat. Change looks on phrase starts (get_song_analysis "phrases", every 4 or 8 bars), not mid-phrase.
  The harmony (key, chords) helps with colour: minor keys suit cooler palettes, major warmer ones; chord
  changes (track "chord") are good moments for colour changes. Riffs that come back are motifs (track
  "motif", pitch = motif number; get_song_analysis instruments.motifs): give each motif its own light
  gesture and repeat it every time the riff plays - that makes the music visible.
- CUES FOR SINGLE MOMENTS. Not everything is a looping pattern: put one-shot clips (trigger "once", the
  clip is the cue) on single moments from the analysis: a drop -> a bright flash on the room ("pulse"
  once on indirect LEDs) + a "ripple" once from the viewer; a build-up -> "rise" from the build start
  exactly to the drop; a drum fill -> a "sweep" once over the fill's duration; a crash -> a short flash.
  Cues make transitions readable and give the show its shape.
- DARK WHERE THE MUSIC IS QUIET, BRIGHT WHERE IT HITS. The contrast between dark and bright is what makes
  a show. Passages without drums or with low loudness stay nearly dark - only the melody / voice glows on
  a few LEDs; the room (indirect LEDs) stays off. Loud parts and drops may be bright, but as accents
  (short flashes, hits), not as permanent washes. Set the show's "dynamics" (0.5-0.8) so quiet passages
  automatically get darker. analyze_light: room_light 0.002-0.03 overall, quiet passages below 0.008,
  bright_p90 several times dark_p10.
- DIRECT VS INDIRECT. The viewer only sees the LEDs in front of them (target {"view": "direct"}); LEDs
  behind or far beside them (target {"view": "indirect"}) are only seen as light on walls and ceiling.
  Put detail (hits, notes, chases, sweeps along a strip) on direct LEDs. Use indirect LEDs for the colour
  of the room in loud parts and for flashes on drops, crashes and big hits. A long strip (hundreds of
  LEDs) lights up the whole room even at 0.1 - keep washes on it rare and dim.
- SMALL, LOCAL ACCENTS. Hits light a few segments of 4-30 LEDs instead of whole strips: kick = bigger,
  warmer; snare = sharper, other colour; hihat = tiny glitter (size 1-3).
- MEASURE IN METRES / LEDS, NOT PER STRIP. Use axis "s" (metres along the strip) for chases, waves and
  gradients along strips, hits.size in LEDs.
- USE THE ROOM. Room axes x, y, z and azimuth / elevation span all strips, so sweeps, rises and waves
  travel from strip to strip.
- VARIETY. Different strips, different roles; something changes every few bars; sections with the same
  label sound alike - give them related looks. Pick 2-3 colours per section that belong together;
  white is an accent. Avoid full rainbows everywhere.

Brightness is PERCEIVED brightness (like sRGB): 0.5 looks half as bright as 1.0, the app converts it to
LED PWM with the calibrated curve. Values below ~0.03 fall into the lowest PWM steps and look identical
or switch off. Power: if get_overview shows budgets, check analyze_power - the limiter dims a whole
controller.

Conventions: metres, z is up, floor at z = 0. Azimuth 0 = straight ahead, negative = left; elevation
positive = up. Times are seconds of the song.
Write custom effects as Python/numpy shaders with write_shader when the library is not enough.
"""

SHOW_FORMAT = """\
Show JSON
{
  "id": "auto", "name": "My show", "song_id": "<song id>", "master": 1.0,
  "layers": [                         # composited bottom (first) to top (last)
    {"name": "Room", "opacity": 1.0, "enabled": true, "clips": [
      {"id": "optional", "start": 0.0, "end": 16.5,          # seconds, end exclusive
       "effect": "noise",                                    # effect id or "shader:<name>"
       "params": {"palette": ["#001a40", "#0050a0"], "brightness": 0.08},
       "target": {"view": "indirect"},                      # omit = all LEDs
       "blend": "normal",                                    # normal | add | max | multiply | subtract
       "opacity": 1.0, "fade_in": 1.0, "fade_out": 0.5}
    ]},
    {"name": "Drums", "clips": [
      {"start": 16.5, "end": 48.0, "effect": "hits", "blend": "max",
       "params": {"trigger": "kick", "palette": ["#40c0ff", "#ffffff"], "count": 3, "size": 12, "decay": 0.2},
       "target": {"tags": ["wall"], "view": "direct"}}
    ]}
  ]
}

Target (which LEDs): {"fixtures": [ids], "tags": [tags], "view": "direct" | "indirect",
                      "where": [{"field": f, "min": a, "max": b}], "invert": false}
  fixtures/tags are OR-ed; view and where-ranges are AND-ed on top. view "direct" = LEDs in the viewer's
  field of view, "indirect" = behind / beside the viewer. Where-fields: x, y, z, distance, s (metres;
  s = along the strip from its first LED), nx, ny, nz, u (0..1), azimuth, elevation (degrees), view (0..1).

Show fields: "master" (0..1 overall), "dynamics" (0..1: how much quiet passages of the song darken the
whole show; 0.5-0.8 recommended).

Parameter values can be animated (number params; keyframes also for colours and points):
  audio binding: {"audio": "low", "min": 0.1, "max": 1.0, "pow": 1.0}
     sources: rms, low, mid, high, onset, beat_phase, bar_phase, beat_decay, bar_decay, onset_decay, section_energy,
              drums, bass, vocals, other (loudness of each instrument), density (drum hits per second, relative),
              tension (rises through a build-up), loudness (smoothed loudness of the song)
  keyframes:     {"keys": [[0, "#ff0000"], [8, "#0000ff"]], "ease": "linear|smooth|step"}  (seconds from clip start)
  lfo:           {"lfo": "sine|triangle|saw|square", "beats": 2, "min": 0, "max": 1, "phase": 0}  (or "seconds": 3)

Triggers (pulse, hits, sweep, ripple; notes takes a "track"): beat, bar, onset, the instrument tracks kick, snare,
hihat, crash, bass, vocal, phrase, keys, lead, fill, build, drop, no_drums, chord, stab, pad, arp - and "once" = one
time at the clip start
(a cue: the clip's start and length are the moment; sweep "once" crosses the room over the whole clip).
"velocity" scales the flash with how loud the hit / note was; "sustain" keeps it lit while the note or passage
lasts. Instrument tracks need an analysis with instruments (get_song_analysis: "instruments").

Brightness is perceived (0.5 = looks half as bright). Base levels 0.03-0.15, accents 0.6-1.0, nothing
below 0.03. Long strips: dimmer.

Colours: "#ff0080", "#f08", names (red, orange, amber, yellow, lime, green, mint, cyan, sky, blue, purple,
violet, magenta, pink, white, warmwhite, black), "hsv(200,1,1)" or [r, g, b] 0..255.
Palettes: a palette name or a list of colours.
Axes (gradient, wave, chase, rainbow, vu, sweep): x, y, z (normalised to the room: 0 = floor/wall,
1 = ceiling/opposite wall - spans all strips), u (0..1 along each strip), s (METRES along each strip:
scale/repeat/count/wavelength become per metre, so long and short strips look alike), azimuth
(left -> right as seen by the viewer), elevation (bottom -> top as seen), distance (near -> far),
radial (room centre outwards), angle (around the room centre), fixture, view, or a vector [dx, dy, dz].
Prefix "-" to reverse, e.g. "-z" = ceiling to floor.
Tempo locking: most moving effects take "beats" (> 0 = one cycle per N beats) instead of "speed".
"""


def _err(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": str(exc)}


CURVES_FOR_AI = ("rms", "low", "mid", "high", "onset", "loudness", "drums", "bass", "vocals", "other", "tension", "brightness")
MOMENT_TRACKS = ("drop", "build", "fill", "crash", "phrase", "no_drums")


def instrument_summary(a, feats: AudioFeatures, start: float, end: float) -> dict[str, Any]:
    """What the instruments do per section, plus the single moments (drops, build-ups, fills ...)."""
    if not a.tracks:
        return {
            "available": False,
            "note": "analysed without instruments: only kick / snare / hihat (approximate). Ask the user to analyse the "
            "song again for instrument tracks.",
        }

    def mean(name: str, s0: float, s1: float) -> float:
        c = feats.curves[name]
        i, j = int(s0 * feats.frame_rate), max(int(s0 * feats.frame_rate) + 1, int(s1 * feats.frame_rate))
        return round(float(np.mean(c[i:j])), 2) if len(c) > 1 else 0.0

    sections = []
    for s in a.sections:
        if s.end <= start or s.start >= end:
            continue
        loud = {k: mean(k, s.start, s.end) for k in ("drums", "bass", "vocals", "other")}
        counted = ("kick", "snare", "bass", "vocal", "keys", "lead")
        counts = {k: sum(s.start <= e[0] < s.end for e in a.tracks.get(k, [])) for k in counted}
        sections.append(
            {
                "start": s.start,
                "end": s.end,
                "name": s.name,
                "loudness": mean("loudness", s.start, s.end),
                "instrument_loudness": loud,
                "leading": max(loud, key=loud.get) if max(loud.values()) > 0.2 else None,
                "events": counts,
            }
        )
    moments = {k: [e for e in a.tracks.get(k, []) if start <= e[0] < end] for k in MOMENT_TRACKS}
    return {
        "available": True,
        "separation": a.stems,
        "meter": f"{a.beats_per_bar}/4",
        "sections": sections,
        "moments": moments,
        "moments_format": "[time, strength, duration, pitch]; drop = the music comes in hard, build = build-up leading "
        "into a drop (ends at the drop), fill = drum fill / roll, phrase = sung passage, no_drums = passage without drums",
        "tracks": {k: len(v) for k, v in a.tracks.items()},
        "harmony": _harmony_summary(a.harmony, start, end),
        "motifs": [
            {**m, "times": [t for t in m["times"] if start <= t < end]}
            for m in a.motifs
            if any(start <= t < end for t in m["times"])
        ],
    }


def _harmony_summary(h: dict | None, start: float, end: float) -> dict | None:
    """Key and the chords in the window; the mode suggests a palette (major: warmer, minor: cooler)."""
    if not h or not h.get("key"):
        return None
    chords = [c for c in h.get("chords", []) if c[0] + c[1] > start and c[0] < end]
    return {
        "key": h["key"],
        "mode": h["mode"],
        "confidence": h["confidence"],
        "chords": chords[:80],
        "chords_format": "[start, duration, name, degree in the key (I = home, V = tension towards I), strength]",
    }


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
            direct = float((table.view[sl] >= 0.5).mean())
            role = (
                "seen directly: rhythm and detail"
                if direct >= 0.85
                else "behind / beside the viewer: room colour, flashes"
                if direct <= 0.15
                else 'partly seen: target {"view": "direct"} for detail, {"view": "indirect"} for room colour'
            )
            out.append(
                {
                    "id": f.id,
                    "name": f.name,
                    "type": f.geometry.type,
                    "tags": f.tags,
                    "led_type": f.led_type.value,
                    "led_count": sl.stop - sl.start,
                    "length_m": length,
                    "first_led": np.round(pos[0], 2).tolist(),
                    "last_led": np.round(pos[-1], 2).tolist(),
                    "bbox_min": np.round(pos.min(axis=0), 2).tolist(),
                    "bbox_max": np.round(pos.max(axis=0), 2).tolist(),
                    "azimuth_range": [round(float(az.min()), 1), round(float(az.max()), 1)],
                    "elevation_range": [round(float(el.min()), 1), round(float(el.max()), 1)],
                    "distance_range": [round(float(dist.min()), 2), round(float(dist.max()), 2)],
                    "azimuth_first_last": [round(float(az[0]), 1), round(float(az[-1]), 1)],
                    "leds_per_m": round((sl.stop - sl.start) / length, 1) if length else None,
                    "direct_view_share": round(direct, 2),
                    "role": role,
                    "note": "long strip: lights the whole room even when dim - keep washes low"
                    if sl.stop - sl.start > 200
                    else None,
                }
            )
        return out

    async def notify(slug: str, show_id: str) -> None:
        await st.show_changed(slug, show_id)

    def load_show(slug: str, show_id: str) -> Show:
        try:
            return st.show_store(slug).get(show_id)
        except KeyError:
            names = [f"{s.id} ({s.name})" for s in st.show_store(slug).list()]
            raise KeyError(f"unknown show {show_id!r}; shows: {names}") from None

    def issues_for(slug: str, p, table, show: Show) -> list[dict[str, Any]]:
        shaders, _ = st.show_store(slug).load_shaders()
        return validate_show(show, p, table, features_for(show), shaders)

    async def save_and_check(slug: str, show: Show) -> dict[str, Any]:
        _, p, table = project_and_table(slug)
        version = st.show_store(slug).save(show, "ai")
        issues = await asyncio.to_thread(issues_for, slug, p, table, show)
        await notify(slug, show.id)
        return {
            "ok": True,
            "show_id": show.id,
            "version": version,
            "layers": [l.name for l in show.layers],
            "clips": sum(len(l.clips) for l in show.layers),
            "issues": issues,
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
            "room": {
                "floor_polygon": p.room.floor,
                "height": p.room.height,
                "bounds": {"x": [x0, x1], "y": [y0, y1], "z": [0, h]},
            },
            "viewer": p.viewer.model_dump(),
            "led_count": table.count,
            "fixtures": fixture_summaries(p, table),
            "tags": sorted({t for f in p.fixtures for t in f.tags}),
            "songs": [
                {"id": s.id, "title": s.title, "artist": s.artist, "duration": s.duration, "analysis": s.status}
                for s in st.songs.list()
            ],
            "shows": [{"id": s.id, "name": s.name, "song_id": s.song_id} for s in st.show_store(slug).list()],
            "shaders": st.show_store(slug).shader_names(),
            "brightness": {
                "model": "perceived 0..1 (0.5 looks half as bright), converted to PWM by the calibration curve",
                "calibration": {
                    t.value: {
                        "curve": c.curve,
                        "min_pwm": c.min_level,
                        "off_below": c.cutoff,
                        "pwm_at": {str(v): round(pwm_of_level(v, c), 1) for v in (0.05, 0.1, 0.25, 0.5, 1.0)},
                    }
                    for t, c in p.calibration.items()
                    if any(f.led_type == t for f in p.fixtures)
                },
                "recommended": {"dark": [0.05, 0.25], "normal": [0.3, 0.7], "accent": [0.8, 1.0], "avoid_below": 0.03},
            },
            "power": {
                "volts": p.power.volts,
                "total_budget_ma": p.power.total_budget_ma,
                "controllers": [
                    {"id": c.id, "name": c.name, "budget_ma": c.budget_ma, "fixtures": [m.fixture_id for m in c.mappings]}
                    for c in p.controllers
                ],
                "full_white_ma": round(
                    sum(
                        p.calibration[f.led_type].ma_per_channel
                        * 3
                        * len(range(table.fixture_slice(f.id).start, table.fixture_slice(f.id).stop))
                        for f in p.fixtures
                    )
                ),
            },
            "coordinates": "metres, z up, floor z=0; azimuth negative = left of viewer, elevation positive = up",
        }

    @mcp.tool()
    def get_led_positions(fixture_id: str, stride: int = 1, project: str | None = None) -> dict[str, Any]:
        """Per-LED data of one fixture in data order: position [x,y,z], azimuth, elevation, distance, u.
        Use stride > 1 to thin out long strips."""
        _, _p, table = project_and_table(project)
        if fixture_id not in table.fixture_ids:
            return _err(KeyError(f"unknown fixture {fixture_id!r}; fixtures: {table.fixture_ids}"))
        sl = table.fixture_slice(fixture_id)
        idx = np.arange(sl.start, sl.stop)[:: max(1, stride)]
        return {
            "fixture_id": fixture_id,
            "count": sl.stop - sl.start,
            "stride": max(1, stride),
            "index": (idx - sl.start).tolist(),
            "pos": np.round(table.pos[idx], 3).tolist(),
            "azimuth": np.round(table.azimuth[idx], 1).tolist(),
            "elevation": np.round(table.elevation[idx], 1).tolist(),
            "distance": np.round(table.distance[idx], 2).tolist(),
            "u": np.round(table.u[idx], 3).tolist(),
        }

    @mcp.tool()
    def get_song_analysis(
        song_id: str, start: float = 0.0, end: float | None = None, resolution_hz: float = 4.0, include_onsets: bool = False
    ) -> dict[str, Any]:
        """Music analysis: bpm, beats, downbeats (bar starts), sections (intro/verse/chorus/bridge/break/build/drop/outro
        with similarity labels and energy), instruments (which instrument leads each section; drops, build-ups, fills,
        crashes, sung phrases), drum hits and curves (rms, low, mid, high, onset, loudness, drums, bass, vocals, other,
        tension; 0..1) resampled to resolution_hz inside [start, end]. Request long songs in windows. Notes and hits of
        each instrument: get_song_events."""
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

        def in_win(xs):
            return [x for x in xs if start <= x < end]

        feats = f
        drums = {k: [round(float(x), 3) for x in v if start <= x < end] for k, v in feats.hits.items()}
        density = [
            {
                "section": s.name,
                "start": s.start,
                **{
                    f"{k}_per_bar": round(sum(s.start <= x < s.end for x in v) / max((s.end - s.start) / (4 * 60 / a.bpm), 1), 2)
                    for k, v in feats.hits.items()
                },
            }
            for s in a.sections
        ]
        out = {
            "song": {"id": song.id, "title": song.title, "artist": song.artist, "duration": a.duration},
            "instruments": instrument_summary(a, feats, start, end),
            "drums": drums,
            "drum_density": density,
            "bpm": a.bpm,
            "beat_period": round(60.0 / a.bpm, 4) if a.bpm else None,
            "window": [start, round(end, 3)],
            "sections": [s.model_dump() for s in a.sections],
            "beats": in_win(a.beats),
            "downbeats": in_win(a.downbeats),
            "phrases": [p for p in a.phrases if start <= p[0] < end],
            "curves": {
                "times": np.round(times, 3).tolist(),
                **{name: [round(f.level(name, float(t)), 2) for t in times] for name in CURVES_FOR_AI},
            },
        }
        if include_onsets:
            out["onsets"] = in_win(a.onsets)
        return out

    @mcp.tool()
    def get_song_events(
        song_id: str, tracks: list[str] | None = None, start: float = 0.0, end: float | None = None, min_strength: float = 0.0
    ) -> dict[str, Any]:
        """Individual events of instrument tracks in [start, end]: each [time s, strength 0..1, duration s, pitch MIDI
        (0 = none)]. Tracks: kick, snare, hihat, crash, bass, vocal, phrase, keys, lead, fill, build, drop, no_drums,
        chord, stab, pad, arp (default: all). Request dense tracks (hihat, vocal, keys, lead) in windows of ~30 s."""
        try:
            st.songs.get(song_id)
        except KeyError:
            return _err(KeyError(f"unknown song {song_id!r}"))
        a = st.songs.analysis(song_id)
        if a is None:
            return _err(ValueError("the song has not been analysed yet"))
        if not a.tracks:
            return {
                "ok": False,
                "error": "this analysis has no instrument tracks yet - ask the user to analyse the song again "
                "(Songs page, right click -> Neu analysieren); kick / snare / hihat are in get_song_analysis",
            }
        end = a.duration if end is None else end
        names = tracks or list(a.tracks)
        unknown = [n for n in names if n not in a.tracks]
        if unknown:
            return _err(KeyError(f"unknown track(s) {unknown}; available: {sorted(a.tracks)}"))
        return {
            "window": [start, end],
            "format": "[time, strength, duration, pitch]",
            "tracks": {n: [e for e in a.tracks[n] if start <= e[0] < end and e[1] >= min_strength] for n in names},
        }

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
        return [
            {
                "id": s.id,
                "name": s.name,
                "song_id": s.song_id,
                "description": s.description,
                "layers": [l.name for l in s.layers],
                "clips": sum(len(l.clips) for l in s.layers),
            }
            for s in st.show_store(slug).list()
        ]

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
    async def create_show(
        name: str,
        song_id: str | None = None,
        template: str = "empty",
        layers: list[dict] | None = None,
        description: str = "",
        project: str | None = None,
    ) -> dict[str, Any]:
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
                p = st.projects.load(slug)
                show = starter_show(name, song_id, analysis, duration, p, build_led_table(p))
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
    def list_show_versions(show_id: str, project: str | None = None) -> dict[str, Any]:
        """Saved versions of a show, newest first (source ui = user, ai = you, restore = rollback)."""
        slug = st.resolve_project(project)
        try:
            show = load_show(slug, show_id)
        except KeyError as exc:
            return _err(exc)
        store = st.show_store(slug)
        if not store.history(show_id).list():
            store.save(show, "system")
        return {"ok": True, "versions": store.history(show_id).list()[:50]}

    @mcp.tool()
    async def restore_show_version(show_id: str, version_id: str, project: str | None = None) -> dict[str, Any]:
        """Roll a show back to an earlier version (the current state stays in the history)."""
        slug = st.resolve_project(project)
        try:
            show = st.show_store(slug).restore(show_id, version_id)
        except KeyError as exc:
            return _err(KeyError(f"unknown show or version: {exc}"))
        await notify(slug, show_id)
        return {"ok": True, "show_id": show.id, "clips": sum(len(l.clips) for l in show.layers)}

    @mcp.tool()
    def list_looks(project: str | None = None) -> list[dict[str, Any]]:
        """Reusable clip groups (built-in and saved by the user). Times are in beats, so a look fits any tempo."""
        from lsg.render.looks import BUILTIN_LOOKS

        slug = st.resolve_project(project)
        return [
            {
                "id": x.id,
                "name": x.name,
                "description": x.description,
                "beats": x.beats,
                "layers": 1 + max(c.layer for c in x.clips),
            }
            for x in [*BUILTIN_LOOKS, *st.show_store(slug).looks()]
        ]

    @mcp.tool()
    async def apply_look(
        show_id: str, look_id: str, at: float, layer: str | None = None, project: str | None = None
    ) -> dict[str, Any]:
        """Insert a look at song time `at` (snapped to the nearest beat). `layer` = name of the lowest layer to use
        (created if missing; additional look layers are added above)."""
        from lsg.render.looks import BUILTIN_LOOKS
        from lsg.render.looks import apply_look as place

        slug = st.resolve_project(project)
        try:
            show = load_show(slug, show_id)
        except KeyError as exc:
            return _err(exc)
        look = next((x for x in [*BUILTIN_LOOKS, *st.show_store(slug).looks()] if x.id == look_id), None)
        if look is None:
            return _err(KeyError(f"unknown look {look_id!r}"))
        feats = features_for(show)
        b0 = round(feats.beat_position(at))
        names = [l.name for l in show.layers]
        if layer and layer not in names:
            show.layers.append(Layer(name=layer))
            names.append(layer)
        li = names.index(layer) if layer else len(show.layers)
        show, ids = place(show, look, feats.time_at_beat(b0), li, lambda b: feats.time_at_beat(b0 + b))
        result = await save_and_check(slug, show)
        result["added"] = ids
        return result

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

    @mcp.tool()
    async def analyze_light(show_id: str, project: str | None = None) -> dict[str, Any]:
        """How bright and how lively a show is: room_light (mean linear light of all LEDs; 0.01-0.04 = dark and
        punchy, > 0.06 = bright and flat), share of lit LEDs, motion between frames, per section, and the
        longest stretch without visible change. Use it to keep shows dark and varied."""
        slug, p, table = project_and_table(project)
        try:
            show = load_show(slug, show_id)
        except KeyError as exc:
            return _err(exc)
        from lsg.render.validate import light_issues, light_report

        def work():
            report = light_report(renderer_for(slug, p, table, show))
            report["hints"] = [i["message"] for i in light_issues(report, show)]
            return report

        return await asyncio.to_thread(work)

    @mcp.tool()
    async def analyze_power(show_id: str, fps: float = 2.0, project: str | None = None) -> dict[str, Any]:
        """Estimated current per controller over the whole show (before limiting), peaks and how long the
        power limiter would dim the output. Use it to keep bright scenes within the power budgets."""
        slug, p, table = project_and_table(project)
        try:
            show = load_show(slug, show_id)
        except KeyError as exc:
            return _err(exc)
        if not p.controllers:
            return {"ok": False, "error": "no controllers configured - power depends on the LED mapping"}

        def work():
            from lsg.output.pipeline import OutputPipeline
            from lsg.output.power import analyse_power

            report = analyse_power(
                renderer_for(slug, p, table, show),
                OutputPipeline(p, table),
                fps=min(max(fps, 0.5), 10.0),
                brightness=st.session.output.brightness,
            )
            report.pop("times")
            report["curves"] = {k: v[:: max(1, int(len(v) / 120))] for k, v in report["curves"].items()}
            report["total_curve"] = report["total_curve"][:: max(1, int(len(report["total_curve"]) / 120))]
            return report

        return {"ok": True, **await asyncio.to_thread(work)}

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
            from lsg.render import shader_host
            from lsg.render.shaders import Shader

            shader = Shader(name, code)
            runner = shader_host.IsolatedShader(shader) if shader_host.ENABLED else shader
            probe = Show(layers=[Layer(clips=[Clip(id="probe", start=0, end=10, effect=f"shader:{name}")])])
            r = Renderer(p, table, probe, AudioFeatures(None, 10), {name: runner})
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
