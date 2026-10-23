// Pure show-editing operations (return new objects, never mutate the input).
import type { Analysis, Clip, EffectInfo, Layer, Show } from "../types";

export const newId = () => Math.random().toString(16).slice(2, 14);

export function allClips(show: Show): { clip: Clip; layer: Layer; li: number }[] {
  return show.layers.flatMap((layer, li) => layer.clips.map((clip) => ({ clip, layer, li })));
}

export function findClip(show: Show, id: string) {
  return allClips(show).find((c) => c.clip.id === id) ?? null;
}

export function mapClips(show: Show, ids: Set<string>, fn: (c: Clip) => Clip): Show {
  return { ...show, layers: show.layers.map((l) => ({ ...l, clips: l.clips.map((c) => (ids.has(c.id) ? fn(c) : c)) })) };
}

export function updateClip(show: Show, id: string, patch: Partial<Clip>): Show {
  return mapClips(show, new Set([id]), (c) => ({ ...c, ...patch }));
}

export function moveClips(show: Show, ids: Set<string>, dt: number, layerDelta: number, duration: number): Show {
  const minStart = Math.min(...allClips(show).filter((c) => ids.has(c.clip.id)).map((c) => c.clip.start));
  const shift = Math.max(dt, -minStart);
  if (layerDelta === 0) {
    return mapClips(show, ids, (c) => {
      const len = c.end - c.start;
      const start = Math.min(Math.max(0, c.start + shift), Math.max(0, duration - len));
      return { ...c, start: round(start), end: round(start + len) };
    });
  }
  const layers = show.layers.map((l) => ({ ...l, clips: [...l.clips] }));
  const moved: { clip: Clip; to: number }[] = [];
  layers.forEach((l, li) => {
    l.clips = l.clips.filter((c) => {
      if (!ids.has(c.id)) return true;
      const len = c.end - c.start;
      const start = Math.max(0, c.start + shift);
      moved.push({ clip: { ...c, start: round(start), end: round(start + len) }, to: Math.min(layers.length - 1, Math.max(0, li + layerDelta)) });
      return false;
    });
  });
  moved.forEach(({ clip, to }) => layers[to].clips.push(clip));
  return { ...show, layers };
}

export function trimClip(show: Show, id: string, edge: "start" | "end", t: number): Show {
  return mapClips(show, new Set([id]), (c) => {
    if (edge === "start") return { ...c, start: round(Math.max(0, Math.min(t, c.end - 0.05))) };
    return { ...c, end: round(Math.max(t, c.start + 0.05)) };
  });
}

export function deleteClips(show: Show, ids: Set<string>): Show {
  return { ...show, layers: show.layers.map((l) => ({ ...l, clips: l.clips.filter((c) => !ids.has(c.id)) })) };
}

export function addClip(show: Show, layerIndex: number, clip: Clip): Show {
  const layers = show.layers.length ? show.layers : [{ id: newId(), name: "Ebene 1", enabled: true, opacity: 1, clips: [] }];
  const li = Math.min(Math.max(0, layerIndex), layers.length - 1);
  return { ...show, layers: layers.map((l, i) => (i === li ? { ...l, clips: [...l.clips, clip] } : l)) };
}

/** Copies placed so the earliest starts at `at`, all into `layerIndex` (or their original layers). */
export function pasteClips(show: Show, clips: { clip: Clip; li: number }[], at: number, duration: number): { show: Show; ids: string[] } {
  if (!clips.length) return { show, ids: [] };
  const first = Math.min(...clips.map((c) => c.clip.start));
  let next = show;
  const ids: string[] = [];
  for (const { clip, li } of clips) {
    const start = round(Math.max(0, at + clip.start - first));
    if (start >= duration) continue;
    const copy = { ...structuredClone(clip), id: newId(), start, end: round(start + clip.end - clip.start) };
    ids.push(copy.id);
    next = addClip(next, li, copy);
  }
  return { show: next, ids };
}

export function newClip(effect: EffectInfo | { id: string }, start: number, length: number): Clip {
  return {
    id: newId(),
    start: round(start),
    end: round(start + length),
    effect: effect.id,
    params: {},
    target: {},
    blend: "normal",
    opacity: 1,
    fade_in: 0,
    fade_out: 0,
  };
}

/** Change the effect of a clip, keeping parameters the new effect also understands. */
export function changeEffect(clip: Clip, effect: string, effects: EffectInfo[]): Clip {
  const info = effects.find((e) => e.id === effect);
  const params = info ? Object.fromEntries(Object.entries(clip.params).filter(([k]) => k in info.params)) : clip.params;
  return { ...clip, effect, params };
}

/** Insert look clips: layer offsets relative to `baseLayer`, missing layers are created on top. */
export function insertLookClips(show: Show, items: { layer: number; clip: Clip }[], baseLayer: number, lookName: string): { show: Show; ids: string[] } {
  let next: Show = { ...show, layers: show.layers.map((l) => ({ ...l, clips: [...l.clips] })) };
  if (!next.layers.length) next = addLayer(next, "Ebene 1");
  const ids: string[] = [];
  for (const { layer, clip } of items) {
    const li = Math.max(0, baseLayer) + layer;
    while (li >= next.layers.length) next = addLayer(next, `${lookName} ${next.layers.length + 1}`);
    const copy = { ...clip, id: newId() };
    ids.push(copy.id);
    next.layers[li].clips.push(copy);
  }
  return { show: next, ids };
}

export function addLayer(show: Show, name?: string): Show {
  return { ...show, layers: [...show.layers, { id: newId(), name: name ?? `Ebene ${show.layers.length + 1}`, enabled: true, opacity: 1, clips: [] }] };
}

export function updateLayer(show: Show, id: string, patch: Partial<Layer>): Show {
  return { ...show, layers: show.layers.map((l) => (l.id === id ? { ...l, ...patch } : l)) };
}

export function deleteLayer(show: Show, id: string): Show {
  return { ...show, layers: show.layers.filter((l) => l.id !== id) };
}

export function moveLayer(show: Show, id: string, delta: number): Show {
  const i = show.layers.findIndex((l) => l.id === id);
  const j = i + delta;
  if (i < 0 || j < 0 || j >= show.layers.length) return show;
  const layers = [...show.layers];
  [layers[i], layers[j]] = [layers[j], layers[i]];
  return { ...show, layers };
}

export const round = (v: number) => Math.round(v * 1000) / 1000;

// ---- snapping ----

export type SnapMode = "off" | "half" | "beat" | "bar";

/** Single moments of the music (drops, build-up starts, fills, crashes, sung phrases). */
export function momentTimes(analysis: Analysis | null): number[] {
  const tr = analysis?.tracks;
  if (!tr) return [];
  const out: number[] = [];
  for (const k of ["drop", "fill", "crash", "phrase"]) for (const e of tr[k] ?? []) out.push(e[0]);
  for (const e of tr.build ?? []) out.push(e[0], e[0] + e[2]);
  return out;
}

export function gridTimes(analysis: Analysis | null, mode: SnapMode, duration: number): number[] {
  if (mode === "off") return [];
  const moments = momentTimes(analysis);
  if (moments.length) return [...gridOnly(analysis, mode, duration), ...moments].sort((a, b) => a - b);
  return gridOnly(analysis, mode, duration);
}

function gridOnly(analysis: Analysis | null, mode: SnapMode, duration: number): number[] {
  if (!analysis || analysis.beats.length < 2) {
    const step = mode === "bar" ? 2 : mode === "beat" ? 0.5 : 0.25;
    return Array.from({ length: Math.ceil(duration / step) + 1 }, (_, i) => i * step);
  }
  if (mode === "bar") return analysis.downbeats;
  if (mode === "beat") return analysis.beats;
  const b = analysis.beats;
  const out: number[] = [];
  for (let i = 0; i < b.length; i++) {
    out.push(b[i]);
    if (i + 1 < b.length) out.push((b[i] + b[i + 1]) / 2);
  }
  return out;
}

/** Nearest grid time within `tolerance` seconds, otherwise t itself. */
export function snap(t: number, grid: number[], tolerance: number): number {
  if (!grid.length) return t;
  let lo = 0,
    hi = grid.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (grid[mid] < t) lo = mid;
    else hi = mid;
  }
  const best = Math.abs(grid[lo] - t) < Math.abs(grid[hi] - t) ? grid[lo] : grid[hi];
  return Math.abs(best - t) <= tolerance ? best : t;
}

/** Length of one bar at time t (for default clip lengths). */
export function barLength(analysis: Analysis | null, t: number): number {
  if (!analysis || analysis.downbeats.length < 2) return analysis?.bpm ? (4 * 60) / analysis.bpm : 2;
  const d = analysis.downbeats;
  for (let i = 0; i + 1 < d.length; i++) if (d[i + 1] > t) return d[i + 1] - d[i];
  return d[d.length - 1] - d[d.length - 2];
}
