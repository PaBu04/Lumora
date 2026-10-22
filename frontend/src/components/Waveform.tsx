import { useEffect, useRef } from "react";
import type { Analysis } from "../types";

export const SECTION_COLORS: Record<string, string> = {
  intro: "#3b82f6",
  verse: "#22c55e",
  chorus: "#ff2d95",
  bridge: "#f59e0b",
  break: "#14b8a6",
  outro: "#8b5cf6",
};

/** Waveform with section bands and beat grid; optional playhead and click-to-seek. */
export function Waveform({
  analysis,
  duration,
  position,
  onSeek,
  height = 44,
  curves = false,
}: {
  analysis: Analysis | null;
  duration: number;
  position?: number;
  onSeek?: (t: number) => void;
  height?: number;
  curves?: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = c.clientWidth,
        h = c.clientHeight;
      if (w === 0 || h === 0) return;
      c.width = w * dpr;
      c.height = h * dpr;
      const ctx = c.getContext("2d")!;
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, w, h);
      const dur = duration || analysis?.duration || 1;
      const x = (t: number) => (t / dur) * w;
      if (analysis) {
        for (const s of analysis.sections) {
          ctx.fillStyle = (SECTION_COLORS[s.name] ?? "#64748b") + "26";
          ctx.fillRect(x(s.start), 0, x(s.end) - x(s.start), h);
          ctx.fillStyle = (SECTION_COLORS[s.name] ?? "#64748b") + "cc";
          ctx.fillRect(x(s.start), 0, Math.max(1, x(s.end) - x(s.start) - 1), 3);
          if (x(s.end) - x(s.start) > 40 && h > 30) {
            ctx.font = "10px system-ui";
            ctx.fillText(`${s.name} ${s.label}`, x(s.start) + 4, 13);
          }
        }
        const mid = h / 2;
        const wf = analysis.waveform;
        ctx.fillStyle = "#7c8aa5";
        for (let px = 0; px < w; px++) {
          const i = Math.floor((px / w) * wf.length);
          const a = wf[i] ?? 0;
          ctx.fillRect(px, mid - a * (mid - 4), 1, Math.max(1, a * (mid - 4) * 2));
        }
        if (curves) {
          const fr = analysis.frame_rate;
          for (const [name, col] of [
            ["low", "#ff2d95"],
            ["mid", "#ffd400"],
            ["high", "#00d4ff"],
          ] as const) {
            const arr = analysis.features[name];
            ctx.strokeStyle = col;
            ctx.globalAlpha = 0.8;
            ctx.beginPath();
            const step = 3;
            for (let px = 0; px < w; px += step) {
              // mean over the frames covered by this pixel bucket (smooths kick spikes)
              const i0 = Math.floor(((px / w) * dur) * fr);
              const i1 = Math.max(i0 + 1, Math.floor((((px + step) / w) * dur) * fr));
              let sum = 0;
              for (let i = i0; i < i1 && i < arr.length; i++) sum += arr[i];
              const v = sum / Math.max(1, Math.min(i1, arr.length) - i0);
              const y = h - 2 - v * (h * 0.45);
              if (px === 0) ctx.moveTo(px, y);
              else ctx.lineTo(px, y);
            }
            ctx.stroke();
            ctx.globalAlpha = 1;
          }
        }
        // beat grid: downbeats stronger
        const beatPx = w / Math.max(analysis.beats.length, 1);
        if (beatPx > 3) {
          ctx.fillStyle = "rgba(255,255,255,0.12)";
          for (const b of analysis.beats) ctx.fillRect(x(b), h - 6, 1, 6);
        }
        ctx.fillStyle = "rgba(255,255,255,0.35)";
        for (const b of analysis.downbeats) ctx.fillRect(x(b), h - 9, 1, 9);
      } else {
        ctx.fillStyle = "#1f2532";
        ctx.fillRect(0, h / 2 - 1, w, 2);
      }
      if (position !== undefined) {
        ctx.fillStyle = "#ff2d95";
        ctx.fillRect(x(position) - 1, 0, 2, h);
      }
    };
    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(c);
    return () => ro.disconnect();
  }, [analysis, duration, position, curves]);

  return (
    <canvas
      ref={canvas}
      style={{ width: "100%", height, display: "block", cursor: onSeek ? "pointer" : "default" }}
      onPointerDown={(e) => {
        if (!onSeek) return;
        const r = (e.target as HTMLCanvasElement).getBoundingClientRect();
        onSeek(((e.clientX - r.left) / r.width) * (duration || analysis?.duration || 0));
      }}
    />
  );
}
