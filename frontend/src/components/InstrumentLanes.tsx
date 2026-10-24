import { useEffect, useRef } from "react";
import { t as t_ } from "../i18n";
import type { Analysis } from "../types";

type Ev = [number, number, number, number];

export const MOMENT_COLORS: Record<string, string> = {
  drop: "#f43f5e",
  build: "#fbbf24",
  fill: "#fb923c",
  crash: "#fde047",
  phrase: "#2dd4bf",
};

/** Colour of riff number n (track "motif"). */
export const motifColor = (n: number) => ["#34d399", "#f472b6", "#38bdf8", "#facc15"][(Math.round(n) - 1) % 4];

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
  /** tracks that light the label up at the playhead */
  active: string[];
}[] = [
  { name: "drums", label: "Schlagzeug", color: "#f87171", curve: "drums", active: ["kick", "snare", "hihat", "crash"] },
  { name: "bass", label: "Bass", color: "#a78bfa", curve: "bass", active: ["bass"] },
  { name: "vocal", label: "Gesang", color: "#2dd4bf", curve: "vocals", active: ["vocal"] },
  { name: "lead", label: "Keys / Synth", color: "#60a5fa", curve: "other", active: ["keys", "lead"] },
  { name: "chords", label: "Akkorde", color: "#e879f9", active: ["chord"] },
  { name: "motifs", label: "Motive", color: "#34d399", active: ["motif"] },
  { name: "moments", label: "Momente", color: "#fbbf24", active: ["fill", "drop", "build"] },
];
const LANE_H = 30;
const LABEL_W = 92;
const HIT_DECAY = 0.15; // seconds a hit keeps glowing

/** Index of the first event at or after t (events are sorted by time). */
function lowerBound(evs: Ev[], t: number): number {
  let lo = 0,
    hi = evs.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (evs[mid][0] < t) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** How strongly a track sounds at t: a held note, or a hit fading out (0..1). */
export function activity(evs: Ev[] | undefined, t: number): number {
  if (!evs?.length) return 0;
  let a = 0;
  // notes can be long, so look back a few events
  for (let i = lowerBound(evs, t + 1e-6) - 1, n = 0; i >= 0 && n < 24; i--, n++) {
    const [s, v, d] = evs[i];
    if (t - s > 30) break;
    const end = s + Math.max(d, 0);
    const level = t <= end ? v : v * Math.exp(-(t - end) / HIT_DECAY);
    a = Math.max(a, level);
  }
  return Math.min(1, a);
}

/** What each instrument does over time: loudness as a soft band, hits as ticks, notes at their pitch,
 * and the single moments (build-ups, drops, fills, crashes). `range` shows only that window of the song;
 * while a position is given the labels light up with what sounds there. */
export function InstrumentLanes({
  analysis,
  duration,
  position,
  range,
  onSeek,
}: {
  analysis: Analysis;
  duration: number;
  position?: number;
  range?: [number, number];
  onSeek?: (t: number) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const dur = duration || analysis.duration || 1;
  const [t0, t1] = range ?? [0, dur];

  useEffect(() => {
    const tracks = (analysis.tracks ?? {}) as Record<string, Ev[]>;
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
      const span = Math.max(t1 - t0, 1e-3);
      const w = W - LABEL_W;
      const x = (t: number) => LABEL_W + ((t - t0) / span) * w;
      const len = (d: number) => (d / span) * w;
      const visible = (name: string, pad = 0) => {
        const evs = tracks[name] ?? [];
        // long notes and build-ups start before the window
        return evs.slice(lowerBound(evs, t0 - pad - 30), lowerBound(evs, t1 + pad)).filter((e) => e[0] + e[2] >= t0 - pad);
      };
      const fr = analysis.frame_rate;
      g.font = "11px system-ui";
      // beat grid when there is room for it
      const beats = analysis.beats.filter((b) => b >= t0 && b <= t1);
      if (beats.length && w / beats.length > 6) {
        g.fillStyle = "rgba(255,255,255,0.05)";
        for (const b of beats) g.fillRect(x(b), 0, 1, H);
      }
      g.fillStyle = "rgba(255,255,255,0.13)";
      for (const b of analysis.downbeats) if (b >= t0 && b <= t1) g.fillRect(x(b), 0, 1, H);

      LANES.forEach((lane, li) => {
        const y0 = li * LANE_H;
        g.fillStyle = li % 2 ? "rgba(255,255,255,0.02)" : "rgba(255,255,255,0.045)";
        g.fillRect(0, y0, W, LANE_H);
        g.save(); // notes and build-ups starting before the window must not run into the label
        g.beginPath();
        g.rect(LABEL_W, y0, w, LANE_H);
        g.clip();
        // instrument loudness as a soft band from the bottom
        const curve = lane.curve ? analysis.features[lane.curve] : undefined;
        if (curve) {
          g.fillStyle = lane.color + "30";
          const step = 2;
          for (let px = 0; px < w; px += step) {
            const i0 = Math.floor((t0 + (px / w) * span) * fr);
            const i1 = Math.max(i0 + 1, Math.floor((t0 + ((px + step) / w) * span) * fr));
            let m = 0;
            for (let i = Math.max(0, i0); i < i1 && i < curve.length; i++) m = Math.max(m, curve[i]);
            const hh = m * (LANE_H - 4);
            g.fillRect(LABEL_W + px, y0 + LANE_H - 2 - hh, step, hh);
          }
        }
        const notes = (name: string, color: string, lo: number, hi: number) => {
          g.fillStyle = color;
          for (const [t, v, d, p] of visible(name)) {
            const y = p > 0 ? y0 + LANE_H - 4 - ((Math.min(hi, Math.max(lo, p)) - lo) / (hi - lo)) * (LANE_H - 8) : y0 + LANE_H / 2;
            g.globalAlpha = 0.35 + 0.65 * v;
            g.fillRect(x(t), y - 1, Math.max(1.5, len(d)), 2.5);
          }
          g.globalAlpha = 1;
        };
        const pitchRange = (name: string): [number, number] => {
          const ps = (tracks[name] ?? [])
            .map((e) => e[3])
            .filter((p) => p > 0)
            .sort((a, b) => a - b);
          if (ps.length < 2) return [36, 84];
          const lo = ps[Math.floor(ps.length * 0.05)],
            hi = ps[Math.floor(ps.length * 0.95)];
          return [lo, Math.max(hi, lo + 5)];
        };
        const tick = Math.max(1, Math.min(3, len(0.03)));
        if (lane.name === "drums") {
          for (const [name, col, top, bot] of [
            ["hihat", "#94a3b8", 0.1, 0.3],
            ["snare", "#facc15", 0.3, 0.65],
            ["kick", "#f87171", 0.6, 0.95],
            ["crash", "#fde047", 0.05, 0.95],
          ] as const) {
            g.fillStyle = col;
            for (const [t, v] of visible(name)) {
              g.globalAlpha = 0.3 + 0.7 * v;
              g.fillRect(x(t), y0 + top * LANE_H, tick, (bot - top) * LANE_H);
            }
          }
          g.globalAlpha = 1;
        } else if (lane.name === "vocal") {
          g.fillStyle = MOMENT_COLORS.phrase + "38";
          for (const [t, , d] of visible("phrase")) g.fillRect(x(t), y0 + 2, len(d), LANE_H - 4);
          notes("vocal", lane.color, ...pitchRange("vocal"));
        } else if (lane.name === "bass") {
          notes(lane.name, lane.color, ...pitchRange(lane.name));
        } else if (lane.name === "lead") {
          // every note (chords stack up) faint, the melody on top bright
          const range = pitchRange(tracks.keys?.length ? "keys" : "lead");
          if (tracks.keys?.length && tracks.keys !== tracks.lead) {
            g.save();
            g.globalAlpha = 0.45;
            notes("keys", "#3b6fb8", ...range);
            g.restore();
          }
          notes("lead", "#93c5fd", ...range);
          // how the keys play: pads (held chords) and arpeggios as bars on top, stabs as ticks
          g.fillStyle = "#c4b5fd";
          for (const [t, v, d] of visible("pad")) {
            g.globalAlpha = 0.25 + 0.4 * v;
            g.fillRect(x(t), y0 + 1, len(d), 3);
          }
          g.fillStyle = "#67e8f9";
          for (const [t, v, d] of visible("arp")) {
            g.globalAlpha = 0.4 + 0.5 * v;
            for (let px = x(t); px < x(t + d); px += 4) g.fillRect(px, y0 + 1, 2, 3);
          }
          g.fillStyle = "#f0abfc";
          for (const [t, v] of visible("stab")) {
            g.globalAlpha = 0.3 + 0.6 * v;
            g.fillRect(x(t), y0 + 1, tick, 5);
          }
          g.globalAlpha = 1;
        } else if (lane.name === "motifs") {
          // recurring riffs: one block per occurrence, colour and row per riff
          for (const [t, v, d, n] of visible("motif")) {
            const row = (Math.round(n) - 1) % 4;
            g.fillStyle = motifColor(n);
            g.globalAlpha = 0.45 + 0.45 * v;
            g.fillRect(x(t) + 0.5, y0 + 3 + row * 6, Math.max(2, len(d) - 1), 5);
            g.globalAlpha = 1;
            if (len(d) > 22) {
              g.fillStyle = "#0b0e14";
              g.font = "9px system-ui";
              g.fillText(`M${Math.round(n)}`, x(t) + 3, y0 + 7.5 + row * 6);
              g.font = "11px system-ui";
            }
          }
        } else if (lane.name === "chords") {
          // chord blocks: hue = root, minor chords darker, the name where there is room
          for (const [t, d, name, degree, v] of analysis.harmony?.chords ?? []) {
            if (t + d < t0 || t > t1) continue;
            const root = (tracks.chord ?? []).find((e) => Math.abs(e[0] - t) < 0.01)?.[3] ?? 60;
            const minor = name.endsWith("m");
            const hue = ((root - 60) % 12) * 30;
            g.fillStyle = `hsla(${hue}, ${minor ? 45 : 70}%, ${minor ? 38 : 52}%, ${0.35 + 0.5 * v})`;
            g.fillRect(x(t) + 0.5, y0 + 3, Math.max(1, len(d) - 1), LANE_H - 6);
            if (len(d) > 26) {
              g.fillStyle = "#fff";
              g.fillText(len(d) > 52 ? `${name} ${degree}` : name, x(t) + 4, y0 + LANE_H / 2 + 4);
            }
          }
        } else if (lane.name === "moments") {
          for (const [t, v, d] of visible("build")) {
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
          for (const [t, v, d] of visible("fill")) {
            g.globalAlpha = 0.4 + 0.6 * v;
            g.fillRect(x(t), y0 + LANE_H - 9, Math.max(2, len(d)), 6);
          }
          g.globalAlpha = 1;
          g.fillStyle = MOMENT_COLORS.crash;
          for (const [t] of visible("crash")) g.fillRect(x(t) - 1, y0 + 3, 2, 7);
          for (const [t, v] of visible("drop")) {
            g.fillStyle = MOMENT_COLORS.drop;
            g.globalAlpha = 0.4 + 0.6 * v;
            g.fillRect(x(t) - 1, y0 + 1, 2.5, LANE_H - 2);
            g.globalAlpha = 1;
            if (v >= 0.8) g.fillText(t_("Drop"), x(t) + 4, y0 + 12);
          }
        }
        g.restore();
        // label, lit by what sounds at the playhead
        const a = position === undefined ? 0 : Math.max(...lane.active.map((k) => activity(tracks[k], position)));
        if (a > 0.02) {
          g.fillStyle = lane.color;
          g.globalAlpha = 0.15 + 0.6 * a;
          g.fillRect(0, y0 + 1, LABEL_W - 4, LANE_H - 2);
          g.globalAlpha = 1;
        }
        g.fillStyle = a > 0.3 ? "#fff" : "#9aa4b8";
        g.fillText(t_(lane.label), 6, y0 + LANE_H / 2 + 4);
      });
      if (position !== undefined && position >= t0 && position <= t1) {
        g.fillStyle = "#fff";
        g.fillRect(x(position) - 0.5, 0, 1.5, H);
      }
    };
    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(c);
    return () => ro.disconnect();
  }, [analysis, t0, t1, position]);

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
      onPointerDown={(e) => {
        if (!onSeek) return;
        const r = e.currentTarget.getBoundingClientRect();
        const f = (e.clientX - r.left - LABEL_W) / (r.width - LABEL_W);
        if (f >= 0) onSeek(Math.min(dur, t0 + f * (t1 - t0)));
      }}
    />
  );
}
