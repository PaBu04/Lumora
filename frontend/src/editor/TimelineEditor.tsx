import { useEffect, useMemo, useRef, useState } from "react";
import { SECTION_COLORS } from "../components/Waveform";
import type { Analysis, EffectInfo, Look, Show } from "../types";
import { formatTime } from "../ui";
import { liveFrame } from "../ws";
import { useStore } from "../store";
import {
  addClip,
  addLayer,
  barLength,
  gridTimes,
  moveClips,
  newClip,
  snap,
  trimClip,
  updateLayer,
  type SnapMode,
} from "./ops";

const LABEL_W = 150;
const ROW_H = 34;
const RULER_H = 28;
const EDGE_PX = 7;

const EFFECT_COLORS: Record<string, string> = {
  solid: "#64748b",
  gradient: "#0ea5e9",
  rainbow: "#a855f7",
  pulse: "#ff2d95",
  strobe: "#cbd5e1",
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

interface Drag {
  kind: "move" | "start" | "end";
  ids: Set<string>;
  primary: string;
  x0: number;
  y0: number;
  origStart: number;
  origEnd: number;
  dt: number;
  dLayer: number;
  edgeT: number;
  moved: boolean;
}

export function TimelineEditor({
  show,
  apply,
  analysis,
  duration,
  selection,
  setSelection,
  selectedLayer,
  setSelectedLayer,
  onSeek,
  errors,
  snapMode,
  zoom,
  setZoom,
  defaultEffect,
  onDropLook,
}: {
  show: Show;
  apply: (fn: (s: Show) => Show) => void;
  analysis: Analysis | null;
  duration: number;
  selection: Set<string>;
  setSelection: (s: Set<string>) => void;
  selectedLayer: string | null;
  setSelectedLayer: (id: string | null) => void;
  onSeek: (t: number) => void;
  errors: Record<string, string>;
  snapMode: SnapMode;
  zoom: number;
  setZoom: (z: number) => void;
  defaultEffect: EffectInfo | { id: string };
  onDropLook: (lookId: string, at: number, layerIndex: number) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [snapLine, setSnapLine] = useState<number | null>(null);
  const t = usePlayhead();
  const dur = Math.max(duration, 1);
  const pxPerSec = (Math.max(200, width - LABEL_W - 4) / dur) * zoom;
  const x = (s: number) => LABEL_W + s * pxPerSec;
  const grid = useMemo(() => gridTimes(analysis, snapMode, dur), [analysis, snapMode, dur]);
  const bars = useMemo(() => gridTimes(analysis, "bar", dur), [analysis, dur]);
  const n = show.layers.length;

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const timeAt = (clientX: number) => {
    const r = wrap.current!.getBoundingClientRect();
    return Math.max(0, (clientX - r.left + wrap.current!.scrollLeft - LABEL_W) / pxPerSec);
  };
  const snapT = (v: number, free: boolean) => (free ? v : snap(v, grid, 10 / pxPerSec));

  // global pointer handling while dragging a clip
  useEffect(() => {
    if (!drag) return;
    const onMove = (e: PointerEvent) => {
      const dx = e.clientX - drag.x0;
      const dy = e.clientY - drag.y0;
      if (!drag.moved && Math.abs(dx) < 3 && Math.abs(dy) < 3) return;
      const free = e.altKey;
      if (drag.kind === "move") {
        let start = snapT(drag.origStart + dx / pxPerSec, free);
        const endSnap = snapT(drag.origEnd + dx / pxPerSec, free);
        if (start === drag.origStart + dx / pxPerSec && endSnap !== drag.origEnd + dx / pxPerSec) start = endSnap - (drag.origEnd - drag.origStart);
        setSnapLine(start !== drag.origStart + dx / pxPerSec ? start : null);
        setDrag({ ...drag, moved: true, dt: start - drag.origStart, dLayer: drag.ids.size === 1 ? -Math.round(dy / ROW_H) : 0 });
      } else {
        const edgeT = snapT((drag.kind === "start" ? drag.origStart : drag.origEnd) + dx / pxPerSec, free);
        setSnapLine(edgeT);
        setDrag({ ...drag, moved: true, edgeT });
      }
    };
    const onUp = () => {
      setSnapLine(null);
      if (drag.moved) {
        if (drag.kind === "move") {
          if (drag.dt !== 0 || drag.dLayer !== 0) apply((s) => moveClips(s, drag.ids, drag.dt, drag.dLayer, dur));
        } else {
          apply((s) => trimClip(s, drag.primary, drag.kind as "start" | "end", drag.edgeT));
        }
      }
      setDrag(null);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  });

  const createAt = (clientX: number, li: number, effect: EffectInfo | { id: string }) => {
    const start = snapT(timeAt(clientX), false);
    const len = Math.min(barLength(analysis, start) * (effect.id === "solid" ? 1 : 2), dur - start);
    if (len <= 0.05) return;
    const clip = newClip(effect, start, len);
    apply((s) => addClip(s.layers.length ? s : addLayer(s, "Ebene 1"), li, clip));
    setSelection(new Set([clip.id]));
  };

  // display order: top row = top layer (last in the list)
  const rows = show.layers.map((layer, li) => ({ layer, li })).reverse();

  return (
    <div
      ref={wrap}
      className="timeline"
      style={{ height: "100%", userSelect: "none" }}
      onWheel={(e) => {
        if (!e.ctrlKey) return;
        e.preventDefault();
        setZoom(Math.min(64, Math.max(1, zoom * (e.deltaY < 0 ? 1.25 : 0.8))));
      }}
    >
      <div style={{ position: "relative", width: LABEL_W + dur * pxPerSec + 20, minHeight: "100%" }}>
        {/* ruler */}
        <div
          className="tl-row"
          style={{ height: RULER_H, cursor: "pointer", position: "sticky", top: 0, zIndex: 4, background: "var(--bg)" }}
          onPointerDown={(e) => {
            onSeek(timeAt(e.clientX));
            const move = (ev: PointerEvent) => onSeek(timeAt(ev.clientX));
            const up = () => {
              window.removeEventListener("pointermove", move);
              window.removeEventListener("pointerup", up);
            };
            window.addEventListener("pointermove", move);
            window.addEventListener("pointerup", up);
          }}
        >
          <div className="tl-label" style={{ fontSize: 11 }} title="Strg + Mausrad: Zoom">
            Zeit {zoom > 1 && <span className="unit" style={{ marginLeft: "auto" }}>{zoom.toFixed(1)}×</span>}
          </div>
          {analysis?.sections.map((s, i) => (
            <div
              key={i}
              style={{
                position: "absolute",
                left: x(s.start),
                width: (s.end - s.start) * pxPerSec,
                top: 2,
                height: 12,
                background: (SECTION_COLORS[s.name] ?? "#64748b") + "40",
                borderLeft: `2px solid ${SECTION_COLORS[s.name] ?? "#64748b"}`,
                fontSize: 9.5,
                paddingLeft: 3,
                overflow: "hidden",
                whiteSpace: "nowrap",
                color: "var(--text-2)",
                lineHeight: "12px",
              }}
            >
              {s.name} {s.label}
            </div>
          ))}
          {bars.map((b, i) =>
            pxPerSec * (bars[1] - bars[0] || 2) > 6 ? (
              <div key={i} style={{ position: "absolute", left: x(b), bottom: 0, height: i % 4 === 0 ? 12 : 6, width: 1, background: "#4a5468" }}>
                {i % 4 === 0 && pxPerSec * 4 * (bars[1] - bars[0] || 2) > 60 && (
                  <span style={{ position: "absolute", left: 3, bottom: 0, fontSize: 9.5, color: "var(--text-3)", whiteSpace: "nowrap" }}>
                    {formatTime(b)}
                  </span>
                )}
              </div>
            ) : null,
          )}
        </div>

        {rows.map(({ layer, li }) => (
          <div
            key={layer.id}
            className="tl-row"
            style={{ height: ROW_H, opacity: layer.enabled ? 1 : 0.45 }}
            onDoubleClick={(e) => {
              if ((e.target as HTMLElement).closest(".tl-clip, .tl-label")) return;
              createAt(e.clientX, li, defaultEffect);
            }}
            onPointerDown={(e) => {
              if ((e.target as HTMLElement).closest(".tl-clip, .tl-label")) return;
              if (!e.ctrlKey && !e.shiftKey) setSelection(new Set());
            }}
            onDragOver={(e) => {
              const types = e.dataTransfer.types;
              if (types.includes("application/x-lsg-effect") || types.includes("application/x-lsg-look")) e.preventDefault();
            }}
            onDrop={(e) => {
              const look = e.dataTransfer.getData("application/x-lsg-look");
              if (look) {
                e.preventDefault();
                onDropLook(look, snapT(timeAt(e.clientX), false), li);
                return;
              }
              const id = e.dataTransfer.getData("application/x-lsg-effect");
              if (id) {
                e.preventDefault();
                createAt(e.clientX, li, { id });
              }
            }}
          >
            <div
              className="tl-label"
              title={layer.name}
              style={{ width: LABEL_W, gap: 6, cursor: "pointer", boxShadow: selectedLayer === layer.id ? "inset 2px 0 0 var(--accent)" : undefined }}
              onClick={() => setSelectedLayer(layer.id)}
              onDoubleClick={() => setRenaming(layer.id)}
            >
              <button
                className="btn ghost small"
                style={{ padding: "0 4px", minWidth: 20 }}
                title={layer.enabled ? "Ebene ausblenden" : "Ebene einblenden"}
                onClick={(e) => {
                  e.stopPropagation();
                  apply((s) => updateLayer(s, layer.id, { enabled: !layer.enabled }));
                }}
              >
                {layer.enabled ? "●" : "○"}
              </button>
              {renaming === layer.id ? (
                <input
                  type="text"
                  autoFocus
                  defaultValue={layer.name}
                  style={{ padding: "2px 4px", fontSize: 12 }}
                  onBlur={(e) => {
                    const name = e.target.value.trim();
                    if (name && name !== layer.name) apply((s) => updateLayer(s, layer.id, { name }));
                    setRenaming(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                    if (e.key === "Escape") setRenaming(null);
                  }}
                />
              ) : (
                <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{layer.name}</span>
              )}
            </div>
            {layer.clips.map((c) => {
              const sel = selection.has(c.id);
              let start = c.start,
                end = c.end,
                dRow = 0;
              if (drag && drag.moved && drag.ids.has(c.id)) {
                if (drag.kind === "move") {
                  start = Math.max(0, c.start + drag.dt);
                  end = start + (c.end - c.start);
                  dRow = Math.max(-li, Math.min(n - 1 - li, drag.dLayer));
                } else if (drag.primary === c.id) {
                  if (drag.kind === "start") start = Math.min(drag.edgeT, c.end - 0.05);
                  else end = Math.max(drag.edgeT, c.start + 0.05);
                }
              }
              const w = Math.max(3, (end - start) * pxPerSec);
              const fadeIn = Math.min(w, c.fade_in * pxPerSec);
              const fadeOut = Math.min(w, c.fade_out * pxPerSec);
              const color = effectColor(c.effect);
              return (
                <div
                  key={c.id}
                  className={`tl-clip${errors[c.id] ? " err" : ""}${sel ? " sel" : ""}`}
                  title={`${c.effect} · ${start.toFixed(2)}–${end.toFixed(2)} s${errors[c.id] ? `\n⚠ ${errors[c.id]}` : ""}\nZiehen: verschieben · Ränder: kürzen · Alt: ohne Einrasten`}
                  style={{
                    left: x(start),
                    width: w,
                    top: 4 - dRow * ROW_H,
                    background: color + (c.opacity < 1 ? "70" : "b0"),
                    cursor: "grab",
                    zIndex: sel ? 2 : 1,
                  }}
                  onPointerDown={(e) => {
                    if (e.button !== 0) return;
                    e.stopPropagation();
                    const r = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
                    const ox = e.clientX - r.left;
                    const kind: Drag["kind"] = ox < EDGE_PX ? "start" : ox > r.width - EDGE_PX ? "end" : "move";
                    let ids = selection;
                    if (e.ctrlKey || e.metaKey || e.shiftKey) {
                      ids = new Set(selection);
                      if (ids.has(c.id)) ids.delete(c.id);
                      else ids.add(c.id);
                      setSelection(ids);
                      return;
                    }
                    if (!ids.has(c.id)) {
                      ids = new Set([c.id]);
                      setSelection(ids);
                    }
                    setDrag({
                      kind,
                      ids: kind === "move" ? ids : new Set([c.id]),
                      primary: c.id,
                      x0: e.clientX,
                      y0: e.clientY,
                      origStart: c.start,
                      origEnd: c.end,
                      dt: 0,
                      dLayer: 0,
                      edgeT: kind === "start" ? c.start : c.end,
                      moved: false,
                    });
                  }}
                >
                  {fadeIn > 2 && (
                    <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: fadeIn, background: "linear-gradient(90deg, rgba(0,0,0,.55), transparent)", pointerEvents: "none" }} />
                  )}
                  {fadeOut > 2 && (
                    <div style={{ position: "absolute", right: 0, top: 0, bottom: 0, width: fadeOut, background: "linear-gradient(270deg, rgba(0,0,0,.55), transparent)", pointerEvents: "none" }} />
                  )}
                  <span style={{ position: "relative", pointerEvents: "none" }}>{c.effect.replace("shader:", "⚙ ")}</span>
                  <div className="tl-edge" style={{ left: 0 }} />
                  <div className="tl-edge" style={{ right: 0 }} />
                </div>
              );
            })}
          </div>
        ))}

        <div className="tl-row" style={{ height: 30 }}>
          <div className="tl-label" style={{ width: LABEL_W }}>
            <button className="btn ghost small" onClick={() => apply((s) => addLayer(s))}>
              + Ebene
            </button>
          </div>
          {show.layers.length === 0 && (
            <span className="hint" style={{ position: "absolute", left: LABEL_W + 12, top: 6 }}>
              Effekt aus der Leiste hierher ziehen oder Doppelklick in eine Ebene
            </span>
          )}
        </div>

        {snapLine !== null && <div className="tl-playhead" style={{ left: x(snapLine), background: "#00d4ff", width: 1 }} />}
        <div className="tl-playhead" style={{ left: x(t) }} />
      </div>
    </div>
  );
}

export function EffectBar({
  effects,
  shaders,
  looks,
  selected,
  onPick,
}: {
  effects: EffectInfo[];
  shaders: string[];
  looks: Look[];
  selected: string;
  onPick: (id: string) => void;
}) {
  const items = [...effects.map((e) => ({ id: e.id, name: e.name, description: e.description })), ...shaders.map((s) => ({ id: `shader:${s}`, name: `⚙ ${s}`, description: "eigener Shader" }))];
  return (
    <div className="effect-bar">
      <span className="unit" style={{ whiteSpace: "nowrap" }}>
        Effekte:
      </span>
      {items.map((e) => (
        <div
          key={e.id}
          className={`effect-chip${selected === e.id ? " active" : ""}`}
          draggable
          title={`${e.description}\nIn eine Ebene ziehen, oder auswählen und Doppelklick in die Timeline`}
          onDragStart={(ev) => {
            ev.dataTransfer.setData("application/x-lsg-effect", e.id);
            ev.dataTransfer.effectAllowed = "copy";
          }}
          onClick={() => onPick(e.id)}
        >
          <span className="swatch" style={{ background: effectColor(e.id) }} />
          {e.name}
        </div>
      ))}
      {looks.length > 0 && (
        <span className="unit" style={{ whiteSpace: "nowrap", marginLeft: 8 }}>
          Looks:
        </span>
      )}
      {looks.map((l) => (
        <div
          key={l.id}
          className="effect-chip look"
          draggable
          title={`${l.description || "eigener Look"}\n${l.beats} Beats · in eine Ebene ziehen`}
          onDragStart={(ev) => {
            ev.dataTransfer.setData("application/x-lsg-look", l.id);
            ev.dataTransfer.effectAllowed = "copy";
          }}
        >
          ✦ {l.name}
        </div>
      ))}
    </div>
  );
}
