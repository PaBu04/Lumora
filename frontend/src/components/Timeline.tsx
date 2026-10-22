import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import type { Analysis, Show } from "../types";
import { liveFrame } from "../ws";
import { SECTION_COLORS } from "./Waveform";

const EFFECT_COLORS: Record<string, string> = {
  solid: "#64748b",
  gradient: "#0ea5e9",
  rainbow: "#a855f7",
  pulse: "#ff2d95",
  strobe: "#f8fafc",
  chase: "#f59e0b",
  wave: "#06b6d4",
  ripple: "#d946ef",
  sparkle: "#facc15",
  fade: "#94a3b8",
  vu: "#22c55e",
  noise: "#3b82f6",
  spotlight: "#fde68a",
  split: "#f97316",
};

export const effectColor = (effect: string) => (effect.startsWith("shader:") ? "#10b981" : (EFFECT_COLORS[effect] ?? "#64748b"));

/** Smooth playhead: follows the frame stream while playing, the state otherwise. */
export function usePlayhead(): number {
  const pb = useStore((s) => s.playback);
  const [t, setT] = useState(pb?.position ?? 0);
  useEffect(() => {
    if (!pb?.playing) {
      setT(pb?.position ?? 0);
      return;
    }
    let raf = 0;
    const tick = () => {
      setT(liveFrame.t);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [pb?.playing, pb?.position]);
  return t;
}

const LABEL_W = 120;

export function Timeline({
  show,
  analysis,
  duration,
  selected,
  onSelect,
  onSeek,
  errors,
}: {
  show: Show;
  analysis: Analysis | null;
  duration: number;
  selected: string | null;
  onSelect: (clipId: string) => void;
  onSeek: (t: number) => void;
  errors: Record<string, string>;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  const [width, setWidth] = useState(800);
  const t = usePlayhead();
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth - LABEL_W - 2));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const dur = Math.max(duration, 1);
  const pxPerSec = (width / dur) * zoom;
  const x = (s: number) => LABEL_W + s * pxPerSec;

  return (
    <div
      ref={wrap}
      className="timeline"
      style={{ height: "100%" }}
      onWheel={(e) => {
        if (!e.ctrlKey) return;
        e.preventDefault();
        setZoom((z) => Math.min(32, Math.max(1, z * (e.deltaY < 0 ? 1.25 : 0.8))));
      }}
    >
      <div style={{ position: "relative", width: LABEL_W + dur * pxPerSec, minHeight: "100%" }}>
        <div
          className="tl-row"
          style={{ height: 22, cursor: "pointer" }}
          onPointerDown={(e) => {
            const r = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
            onSeek(Math.max(0, (e.clientX - r.left - LABEL_W) / pxPerSec));
          }}
        >
          <div className="tl-label" style={{ fontSize: 11 }} title="Strg + Mausrad: Zoom">
            <span>Song</span>
            {zoom > 1 && (
              <span className="unit" style={{ marginLeft: "auto" }}>
                {zoom.toFixed(1)}×
              </span>
            )}
          </div>
          {analysis?.sections.map((s, i) => (
            <div
              key={i}
              style={{
                position: "absolute",
                left: x(s.start),
                width: (s.end - s.start) * pxPerSec,
                top: 3,
                bottom: 3,
                background: (SECTION_COLORS[s.name] ?? "#64748b") + "40",
                borderLeft: `2px solid ${SECTION_COLORS[s.name] ?? "#64748b"}`,
                fontSize: 10,
                paddingLeft: 4,
                overflow: "hidden",
                whiteSpace: "nowrap",
                color: "var(--text-2)",
              }}
            >
              {s.name} {s.label}
            </div>
          ))}
        </div>
        {show.layers
          .slice()
          .reverse()
          .map((layer) => (
            <div key={layer.id} className="tl-row" style={{ opacity: layer.enabled ? 1 : 0.4 }}>
              <div className="tl-label" title={layer.name}>
                {layer.name}
              </div>
              {layer.clips.map((c) => (
                <div
                  key={c.id}
                  className={`tl-clip${errors[c.id] ? " err" : ""}${selected === c.id ? " sel" : ""}`}
                  title={`${c.effect} ${c.start.toFixed(2)}–${c.end.toFixed(2)} s${errors[c.id] ? `\n⚠ ${errors[c.id]}` : ""}`}
                  style={{
                    left: x(c.start),
                    width: Math.max(2, (c.end - c.start) * pxPerSec),
                    background: effectColor(c.effect) + "b0",
                  }}
                  onClick={() => onSelect(c.id)}
                >
                  {c.effect}
                </div>
              ))}
            </div>
          ))}
        <div className="tl-playhead" style={{ left: x(t) }} />
      </div>
    </div>
  );
}
