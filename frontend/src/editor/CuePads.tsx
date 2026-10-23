import { useEffect, useRef, useState } from "react";
import type { Analysis, Clip, Show, Target } from "../types";
import { liveFrame } from "../ws";
import { useStore } from "../store";
import { newId, round } from "./ops";

/** One-shot effects that can be played in by hand while the song runs (keys 1-7). */
interface Pad {
  key: string;
  label: string;
  hint: string;
  effect: string;
  params: Record<string, unknown>;
  target: Target;
  blend: Clip["blend"];
  /** clip length in beats (null: until the next drop, at most 8 bars) */
  beats: number | null;
}

const PADS: Pad[] = [
  {
    key: "1",
    label: "Blitz",
    hint: "kurzer Blitz auf allen LEDs",
    effect: "pulse",
    params: { decay: 0.3 },
    target: {},
    blend: "add",
    beats: 2,
  },
  {
    key: "2",
    label: "Raumblitz",
    hint: "Blitz nur auf den LEDs hinter / neben dir – färbt den Raum",
    effect: "pulse",
    params: { decay: 0.6 },
    target: { view: "indirect" },
    blend: "add",
    beats: 3,
  },
  {
    key: "3",
    label: "Ring",
    hint: "ein Ring breitet sich von dir aus durch den Raum",
    effect: "ripple",
    params: { center: "viewer", speed: 5, width: 0.5, decay: 1.6 },
    target: {},
    blend: "add",
    beats: 4,
  },
  {
    key: "4",
    label: "Wisch ↑",
    hint: "ein Lichtband vom Boden zur Decke",
    effect: "sweep",
    params: { axis: "z", width: 0.15, tail: 0.4 },
    target: {},
    blend: "add",
    beats: 2,
  },
  {
    key: "5",
    label: "Wisch →",
    hint: "ein Lichtband von links nach rechts durch dein Blickfeld",
    effect: "sweep",
    params: { axis: "azimuth", width: 0.12, tail: 0.4 },
    target: { view: "direct" },
    blend: "add",
    beats: 2,
  },
  {
    key: "6",
    label: "Funkeln",
    hint: "kurzes Glitzern einzelner LEDs",
    effect: "sparkle",
    params: { density: 0.12, decay: 0.12, rate: 24 },
    target: {},
    blend: "add",
    beats: 2,
  },
  {
    key: "7",
    label: "Rise",
    hint: "Build-up: Licht steigt bis zum nächsten Drop (sonst 4 Takte)",
    effect: "rise",
    params: { flicker: 0.6, curve: 2 },
    target: { view: "direct" },
    blend: "add",
    beats: null,
  },
];

type Quant = "hit" | "beat" | "half" | "off";
const ONE_SHOT = new Set(["pulse", "ripple", "sweep", "hits"]); // effects with trigger "once"
const REACTION = 0.06; // seconds: a key press comes a little after the hit you heard

function nearest(t: number, marks: number[], tol: number): number {
  let best = t,
    d = tol;
  for (const m of marks) {
    const dd = Math.abs(m - t);
    if (dd < d) {
      d = dd;
      best = m;
    }
  }
  return best;
}

export function CuePads({
  analysis,
  duration,
  apply,
  onAdded,
}: {
  analysis: Analysis | null;
  duration: number;
  apply: (fn: (s: Show) => Show) => void;
  onAdded: (id: string) => void;
}) {
  const [color, setColor] = useState("#ffffff");
  const [quant, setQuant] = useState<Quant>("hit");
  const [flash, setFlash] = useState<string | null>(null);
  const ref = useRef({ color, quant, analysis, duration });
  ref.current = { color, quant, analysis, duration };

  const fire = (pad: Pad) => {
    const { color, quant, analysis, duration } = ref.current;
    const pb = useStore.getState().playback;
    const playing = !!pb?.playing;
    let t = (playing ? liveFrame.t - REACTION : (pb?.position ?? 0)) || 0;
    const beat = analysis?.bpm ? 60 / analysis.bpm : 0.5;
    if (analysis && quant !== "off") {
      if (quant === "hit") {
        const hits = ["kick", "snare", "crash", "drop"].flatMap((k) =>
          (analysis.tracks?.[k] ?? []).map((e) => e[0]),
        );
        t = nearest(t, hits.length ? hits : analysis.beats, 0.15);
      } else {
        const grid =
          quant === "beat"
            ? analysis.beats
            : analysis.beats.flatMap((b, i, a) =>
                i + 1 < a.length ? [b, (b + a[i + 1]) / 2] : [b],
              );
        t = nearest(t, grid, beat);
      }
    }
    t = Math.max(0, round(t));
    let len = (pad.beats ?? 0) * beat;
    if (pad.beats === null) {
      const drops = (analysis?.tracks?.drop ?? [])
        .map((e) => e[0])
        .filter((d) => d > t + 1 && d - t <= 32 * beat);
      len = drops.length ? drops[0] - t : 16 * beat;
    }
    const end = round(Math.min(duration || t + len, t + len));
    if (end - t < 0.05) return;
    const clip: Clip = {
      id: newId(),
      start: t,
      end,
      effect: pad.effect,
      params: {
        ...pad.params,
        trigger: "once",
        ...(pad.effect === "sparkle" ? { palette: [color] } : { color }),
      },
      target: pad.target,
      blend: pad.blend,
      opacity: 1,
      fade_in: 0,
      fade_out: pad.effect === "sparkle" ? round(len / 2) : 0,
    };
    if (!ONE_SHOT.has(pad.effect)) delete clip.params.trigger; // sparkle / rise play over the clip anyway
    apply((s) => {
      const idx = s.layers.findIndex((l) => l.name === "Cues");
      if (idx >= 0)
        return {
          ...s,
          layers: s.layers.map((l, i) =>
            i === idx ? { ...l, clips: [...l.clips, clip] } : l,
          ),
        };
      return {
        ...s,
        layers: [
          ...s.layers,
          {
            id: newId(),
            name: "Cues",
            enabled: true,
            opacity: 1,
            clips: [clip],
          },
        ],
      };
    });
    onAdded(clip.id);
    setFlash(pad.key);
    setTimeout(() => setFlash((k) => (k === pad.key ? null : k)), 180);
  };

  const fireRef = useRef(fire);
  fireRef.current = fire;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (
        e.ctrlKey ||
        e.metaKey ||
        e.altKey ||
        (e.target as HTMLElement).closest("input, textarea, select")
      )
        return;
      const pad = PADS.find((p) => p.key === e.key);
      if (pad) {
        e.preventDefault();
        fireRef.current(pad);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div
      className="cue-pads"
      title="Einzelne Effekte einspielen: während der Song läuft klicken oder Tasten 1–7 drücken"
    >
      <span className="unit" style={{ whiteSpace: "nowrap" }}>
        Cues
      </span>
      {PADS.map((p) => (
        <button
          key={p.key}
          className={`btn small cue${flash === p.key ? " fired" : ""}`}
          title={`${p.hint} (Taste ${p.key})`}
          onClick={() => fire(p)}
        >
          <kbd>{p.key}</kbd> {p.label}
        </button>
      ))}
      <input
        type="color"
        value={color}
        title="Farbe der Cues"
        onChange={(e) => setColor(e.target.value)}
      />
      <select
        value={quant}
        title="Einrasten der Cues"
        style={{ width: 130, flex: "none" }}
        onChange={(e) => setQuant(e.target.value as Quant)}
      >
        <option value="hit">auf Schlag</option>
        <option value="beat">auf Beat</option>
        <option value="half">auf ½ Beat</option>
        <option value="off">frei</option>
      </select>
    </div>
  );
}
