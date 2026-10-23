import { useEffect, useRef } from "react";
import type { Analysis } from "../types";

type Ev = [number, number, number, number];

export const MOMENT_COLORS: Record<string, string> = {
  drop: "#f43f5e",
  build: "#fbbf24",
  fill: "#fb923c",
  crash: "#fde047",
  phrase: "#2dd4bf",
};

export const MOMENT_LABELS: Record<string, string> = {
  drop: "Drop",
  build: "Build-up",
  fill: "Fill",
  crash: "Crash",
  phrase: "Gesang",
};

const LANES: {
  name: string;
  label: string;
  color: string;
  curve?: "drums" | "bass" | "vocals" | "other";
}[] = [
  { name: "drums", label: "Schlagzeug", color: "#f87171", curve: "drums" },
  { name: "bass", label: "Bass", color: "#a78bfa", curve: "bass" },
  { name: "vocal", label: "Gesang", color: "#2dd4bf", curve: "vocals" },
  { name: "lead", label: "Keys / Synth", color: "#60a5fa", curve: "other" },
  { name: "moments", label: "Momente", color: "#fbbf24" },
];
const LANE_H = 30;
const LABEL_W = 92;

/** What each instrument does over time: loudness as a soft band, hits as ticks, notes at their pitch,
 * and the single moments (build-ups, drops, fills, crashes). */
export function InstrumentLanes({
  analysis,
  duration,
  position,
  onSeek,
}: {
  analysis: Analysis;
  duration: number;
  position?: number;
  onSeek?: (t: number) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const tracks = analysis.tracks ?? {};
    const c = canvas.current;
    if (!c) return;
    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const W = c.clientWidth,
        H = c.clientHeight;
      if (!W || !H) return;
      c.width = W * dpr;
      c.height = H * dpr;
      const g = c.getContext("2d")!;
      g.scale(dpr, dpr);
      g.clearRect(0, 0, W, H);
      const dur = duration || analysis.duration || 1;
      const w = W - LABEL_W;
      const x = (t: number) => LABEL_W + (t / dur) * w;
      const fr = analysis.frame_rate;
      g.font = "11px system-ui";
      LANES.forEach((lane, li) => {
        const y0 = li * LANE_H;
        g.fillStyle =
          li % 2 ? "rgba(255,255,255,0.02)" : "rgba(255,255,255,0.045)";
        g.fillRect(0, y0, W, LANE_H);
        g.fillStyle = "#9aa4b8";
        g.fillText(lane.label, 6, y0 + LANE_H / 2 + 4);
        // instrument loudness as a soft band from the bottom
        const curve = lane.curve ? analysis.features[lane.curve] : undefined;
        if (curve) {
          g.fillStyle = lane.color + "30";
          const step = 2;
          for (let px = 0; px < w; px += step) {
            const i0 = Math.floor((px / w) * dur * fr);
            const i1 = Math.max(
              i0 + 1,
              Math.floor(((px + step) / w) * dur * fr),
            );
            let m = 0;
            for (let i = i0; i < i1 && i < curve.length; i++)
              m = Math.max(m, curve[i]);
            const hh = m * (LANE_H - 4);
            g.fillRect(LABEL_W + px, y0 + LANE_H - 2 - hh, step, hh);
          }
        }
        const notes = (name: string, color: string, lo: number, hi: number) => {
          const evs = (tracks[name] ?? []) as Ev[];
          g.fillStyle = color;
          for (const [t, v, d, p] of evs) {
            const y =
              p > 0
                ? y0 +
                  LANE_H -
                  4 -
                  ((Math.min(hi, Math.max(lo, p)) - lo) / (hi - lo)) *
                    (LANE_H - 8)
                : y0 + LANE_H / 2;
            g.globalAlpha = 0.35 + 0.65 * v;
            g.fillRect(x(t), y - 1, Math.max(1.5, (d / dur) * w), 2.5);
          }
          g.globalAlpha = 1;
        };
        const pitchRange = (name: string): [number, number] => {
          const ps = ((tracks[name] ?? []) as Ev[])
            .map((e) => e[3])
            .filter((p) => p > 0)
            .sort((a, b) => a - b);
          if (ps.length < 2) return [36, 84];
          const lo = ps[Math.floor(ps.length * 0.05)],
            hi = ps[Math.floor(ps.length * 0.95)];
          return [lo, Math.max(hi, lo + 5)];
        };
        if (lane.name === "drums") {
          for (const [name, col, top, bot] of [
            ["hihat", "#94a3b8", 0.1, 0.3],
            ["snare", "#facc15", 0.3, 0.65],
            ["kick", "#f87171", 0.6, 0.95],
            ["crash", "#fde047", 0.05, 0.95],
          ] as const) {
            g.fillStyle = col;
            for (const [t, v] of (tracks[name] ?? []) as Ev[]) {
              g.globalAlpha = 0.3 + 0.7 * v;
              g.fillRect(x(t), y0 + top * LANE_H, 1, (bot - top) * LANE_H);
            }
          }
          g.globalAlpha = 1;
        } else if (lane.name === "vocal") {
          g.fillStyle = MOMENT_COLORS.phrase + "38";
          for (const [t, , d] of (tracks.phrase ?? []) as Ev[])
            g.fillRect(x(t), y0 + 2, (d / dur) * w, LANE_H - 4);
          notes("vocal", lane.color, ...pitchRange("vocal"));
        } else if (lane.name === "bass" || lane.name === "lead") {
          notes(lane.name, lane.color, ...pitchRange(lane.name));
        } else if (lane.name === "moments") {
          for (const [t, v, d] of (tracks.build ?? []) as Ev[]) {
            const grd = g.createLinearGradient(x(t), 0, x(t + d), 0);
            grd.addColorStop(0, MOMENT_COLORS.build + "00");
            grd.addColorStop(1, MOMENT_COLORS.build + "cc");
            g.fillStyle = grd;
            g.beginPath();
            g.moveTo(x(t), y0 + LANE_H - 3);
            g.lineTo(x(t + d), y0 + 3 + (1 - v) * 8);
            g.lineTo(x(t + d), y0 + LANE_H - 3);
            g.fill();
          }
          g.fillStyle = MOMENT_COLORS.fill;
          for (const [t, v, d] of (tracks.fill ?? []) as Ev[]) {
            g.globalAlpha = 0.4 + 0.6 * v;
            g.fillRect(x(t), y0 + LANE_H - 9, Math.max(2, (d / dur) * w), 6);
          }
          g.globalAlpha = 1;
          g.fillStyle = MOMENT_COLORS.crash;
          for (const [t] of (tracks.crash ?? []) as Ev[])
            g.fillRect(x(t) - 1, y0 + 3, 2, 7);
          for (const [t, v] of (tracks.drop ?? []) as Ev[]) {
            g.fillStyle = MOMENT_COLORS.drop;
            g.globalAlpha = 0.4 + 0.6 * v;
            g.fillRect(x(t) - 1, y0 + 1, 2.5, LANE_H - 2);
            g.globalAlpha = 1;
            if (v >= 0.8) g.fillText("Drop", x(t) + 4, y0 + 12);
          }
        }
      });
      if (position !== undefined) {
        g.fillStyle = "#fff";
        g.fillRect(x(position) - 0.5, 0, 1.5, H);
      }
    };
    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(c);
    return () => ro.disconnect();
  }, [analysis, duration, position]);

  return (
    <canvas
      ref={canvas}
      className="instrument-lanes"
      style={{
        width: "100%",
        height: LANES.length * LANE_H,
        display: "block",
        cursor: onSeek ? "pointer" : "default",
      }}
      onClick={(e) => {
        if (!onSeek) return;
        const r = e.currentTarget.getBoundingClientRect();
        const f = (e.clientX - r.left - LABEL_W) / (r.width - LABEL_W);
        if (f >= 0) onSeek(f * (duration || analysis.duration));
      }}
    />
  );
}
