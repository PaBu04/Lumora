"""Export a show as an xLights / Falcon Player package: .fseq + audio + channel map."""

import json
import re
import zipfile
from pathlib import Path

from lsg.output.fseq import write_fseq
from lsg.output.pipeline import OutputPipeline
from lsg.render.engine import Renderer

README = """Light Show Generator export
===========================

{show}.fseq      FSEQ v2 sequence ({fps} FPS, {channels} channels{compressed}), values already include
                 the calibration curve and power limits - play them unchanged
{audio}
channels.json    which channel range belongs to which WLED controller

Falcon Player (FPP): upload the .fseq to "Sequences" and the audio to "Music", then create
a playlist entry "Media + Sequence". Configure the outputs (e.g. DDP to every WLED) with the
start channels listed in channels.json (channel numbers are 1-based).

xLights: File > Import or open the .fseq in the sequence player; the channel map tells which
model / controller each range belongs to.
"""


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip() or "show"


def export_show(
    renderer: Renderer, out_zip: Path, fps: int = 40, brightness: float = 1.0, audio: Path | None = None, compress: bool = True
) -> dict:
    project, table = renderer.project, renderer.table
    pipeline = OutputPipeline(project, table)
    if not pipeline.plans:
        raise ValueError("no controllers configured - the channel layout follows the controller mapping")
    step_ms = round(1000 / fps)
    duration = max(renderer.duration, step_ms / 1000)
    frame_count = int(duration * 1000 // step_ms)

    layout, start = [], 0
    for plan in pipeline.plans:
        ch = plan.pixel_count * (4 if plan.controller.rgbw else 3)
        layout.append(
            {
                "controller": plan.controller.name,
                "host": plan.controller.host,
                "rgbw": plan.controller.rgbw,
                "pixels": plan.pixel_count,
                "start_channel": start + 1,
                "channels": ch,
            }
        )
        start += ch
    channels = start

    def frames():
        for i in range(frame_count):
            frame = renderer.render(i * step_ms / 1000)
            outputs, _ = pipeline.encode_all(lambda c, f=frame: f, brightness)
            yield b"".join(o.data for o in outputs)

    name = _safe(renderer.show.name)
    tmp = out_zip.with_suffix(".fseq.tmp")
    media = f"{name}{audio.suffix}" if audio else None
    summary = write_fseq(tmp, frames(), channels, frame_count, step_ms, media=media, compress=compress)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(tmp, f"{name}.fseq", compress_type=zipfile.ZIP_STORED if summary["compressed"] else zipfile.ZIP_DEFLATED)
        if audio:
            z.write(audio, media, compress_type=zipfile.ZIP_STORED)
        z.writestr(
            "channels.json", json.dumps({"fps": fps, "step_ms": step_ms, "frames": frame_count, "outputs": layout}, indent=2)
        )
        z.writestr(
            "README.txt",
            README.format(
                show=name,
                fps=fps,
                channels=channels,
                compressed=", zstd" if summary["compressed"] else "",
                audio=f"{media:<16} the song (FPP media file)" if media else "",
            ),
        )
    tmp.unlink(missing_ok=True)
    return {**summary, "layout": layout, "file": out_zip.name}
