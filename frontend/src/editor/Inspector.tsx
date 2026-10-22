import { useEffect, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import type { Clip, EffectInfo, Layer, Look, Show, Target } from "../types";
import { Field, NumberInput, Vec3Input } from "../ui";
import { changeEffect, deleteClips, deleteLayer, findClip, mapClips, moveLayer, round, updateClip, updateLayer } from "./ops";

type ParamSchema = EffectInfo["params"][string];
type Dyn = { audio?: string; lfo?: string; keys?: [number, unknown][]; [k: string]: unknown };

const AXES = ["x", "y", "z", "u", "azimuth", "elevation", "distance", "radial", "angle", "fixture"];
const AXIS_LABEL: Record<string, string> = {
  x: "x (Raum)",
  y: "y (Raum)",
  z: "z (Höhe)",
  u: "entlang Strip",
  azimuth: "links → rechts (Betrachter)",
  elevation: "unten → oben (Betrachter)",
  distance: "nah → fern",
  radial: "Raummitte → außen",
  angle: "um die Raummitte",
  fixture: "je Strip",
};
const AUDIO = ["rms", "low", "mid", "high", "onset", "beat_phase", "bar_phase", "beat_decay", "bar_decay", "onset_decay", "section_energy"];
const AUDIO_LABEL: Record<string, string> = {
  rms: "Lautstärke",
  low: "Bass",
  mid: "Mitten",
  high: "Höhen",
  onset: "Anschläge",
  beat_phase: "Beat-Phase",
  bar_phase: "Takt-Phase",
  beat_decay: "Beat-Impuls",
  bar_decay: "Takt-Impuls",
  onset_decay: "Anschlag-Impuls",
  section_energy: "Abschnitts-Energie",
};
const NAMED: Record<string, string> = {
  black: "#000000", white: "#ffffff", warmwhite: "#ffb46b", red: "#ff0000", orange: "#ff6000", amber: "#ffa000",
  yellow: "#ffd800", lime: "#80ff00", green: "#00ff00", mint: "#00ff80", cyan: "#00ffff", sky: "#0080ff",
  blue: "#0000ff", purple: "#8000ff", violet: "#b000ff", magenta: "#ff00ff", pink: "#ff0080",
};
const BLENDS: [string, string][] = [
  ["normal", "normal (überdecken)"],
  ["add", "addieren (aufhellen)"],
  ["max", "Maximum"],
  ["multiply", "multiplizieren (abdunkeln)"],
  ["subtract", "subtrahieren"],
];

export function toHex(v: unknown): string | null {
  if (typeof v === "string") {
    const s = v.trim().toLowerCase();
    if (NAMED[s]) return NAMED[s];
    if (/^#?[0-9a-f]{6}$/.test(s)) return s.startsWith("#") ? s : `#${s}`;
    if (/^#?[0-9a-f]{3}$/.test(s)) return `#${s.replace("#", "").split("").map((c) => c + c).join("")}`;
  }
  if (Array.isArray(v) && v.length === 3) return `#${v.map((c) => Math.round(Number(c)).toString(16).padStart(2, "0")).join("")}`;
  return null;
}

function modeOf(v: unknown): "value" | "audio" | "lfo" | "keys" {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    const d = v as Dyn;
    if (d.audio) return "audio";
    if (d.lfo) return "lfo";
    if (d.keys) return "keys";
  }
  return "value";
}

function ValueEditor({ schema, value, onChange, palettes }: { schema: ParamSchema; value: unknown; onChange: (v: unknown) => void; palettes: Record<string, string[]> }) {
  switch (schema.type) {
    case "number": {
      const v = typeof value === "number" ? value : Number(schema.default);
      const min = schema.min ?? 0;
      const max = schema.max ?? Math.max(1, v * 4);
      const sliderMax = Math.min(max, Math.max(1, min + (max - min > 50 ? 20 : max - min)));
      return (
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input type="range" className="grow" min={min} max={Math.max(sliderMax, v)} step={(sliderMax - min) / 200} value={v} onChange={(e) => onChange(round(+e.target.value))} />
          <div style={{ width: 70 }}>
            <NumberInput value={v} min={schema.min} max={schema.max} step={0.01} onChange={onChange} />
          </div>
        </div>
      );
    }
    case "color": {
      const hex = toHex(value ?? schema.default);
      return (
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input type="color" value={hex ?? "#ffffff"} onChange={(e) => onChange(e.target.value)} />
          <input type="text" value={String(value ?? schema.default)} onChange={(e) => onChange(e.target.value)} />
        </div>
      );
    }
    case "palette": {
      const v = value ?? schema.default;
      const custom = Array.isArray(v);
      return (
        <div>
          <select
            value={custom ? "__custom__" : String(v)}
            onChange={(e) => onChange(e.target.value === "__custom__" ? (palettes[String(v)] ?? ["#ff0080", "#00d4ff"]) : e.target.value)}
          >
            {Object.keys(palettes).map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
            <option value="__custom__">eigene Farben…</option>
          </select>
          <div className="row" style={{ marginTop: 6, gap: 4 }}>
            {(custom ? (v as unknown[]) : (palettes[String(v)] ?? [])).map((c, i) => (
              <span key={i} className="row" style={{ gap: 0 }}>
                <input
                  type="color"
                  disabled={!custom}
                  value={toHex(c) ?? "#ffffff"}
                  onChange={(e) => {
                    const list = [...(v as unknown[])];
                    list[i] = e.target.value;
                    onChange(list);
                  }}
                />
                {custom && (v as unknown[]).length > 1 && (
                  <button className="btn ghost small" style={{ padding: "0 3px" }} onClick={() => onChange((v as unknown[]).filter((_, j) => j !== i))}>
                    ×
                  </button>
                )}
              </span>
            ))}
            {custom && (
              <button className="btn small" onClick={() => onChange([...(v as unknown[]), "#ffffff"])}>
                +
              </button>
            )}
          </div>
        </div>
      );
    }
    case "enum":
      return (
        <select value={String(value ?? schema.default)} onChange={(e) => onChange(e.target.value)}>
          {schema.options?.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      );
    case "bool":
      return <input type="checkbox" checked={Boolean(value ?? schema.default)} onChange={(e) => onChange(e.target.checked)} />;
    case "axis": {
      const v = value ?? schema.default;
      const isVec = Array.isArray(v);
      const name = isVec ? "__vec__" : String(v).replace(/^-/, "");
      const rev = !isVec && String(v).startsWith("-");
      return (
        <div>
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <select value={name} onChange={(e) => onChange(e.target.value === "__vec__" ? [1, 0, 0] : (rev ? "-" : "") + e.target.value)}>
              {AXES.map((a) => (
                <option key={a} value={a}>
                  {AXIS_LABEL[a]}
                </option>
              ))}
              <option value="__vec__">Richtung (Vektor)</option>
            </select>
            {!isVec && (
              <label className="row unit" title="Richtung umkehren">
                <input type="checkbox" checked={rev} onChange={(e) => onChange((e.target.checked ? "-" : "") + name)} />⇄
              </label>
            )}
          </div>
          {isVec && <Vec3Input value={v as [number, number, number]} step={0.1} onChange={onChange} />}
        </div>
      );
    }
    case "point": {
      const v = value ?? schema.default;
      const isVec = Array.isArray(v);
      return (
        <div>
          <select value={isVec ? "__xyz__" : String(v)} onChange={(e) => onChange(e.target.value === "__xyz__" ? [1, 1, 1] : e.target.value)}>
            <option value="viewer">Betrachter</option>
            <option value="center">Raummitte</option>
            <option value="__xyz__">Punkt (x, y, z)</option>
          </select>
          {isVec && <Vec3Input value={v as [number, number, number]} onChange={onChange} />}
        </div>
      );
    }
    default:
      return <input type="text" value={JSON.stringify(value ?? schema.default)} readOnly />;
  }
}

function ParamControl({
  name,
  schema,
  value,
  onChange,
  palettes,
  clipTime,
}: {
  name: string;
  schema: ParamSchema;
  value: unknown;
  onChange: (v: unknown | undefined) => void;
  palettes: Record<string, string[]>;
  clipTime: number;
}) {
  const mode = modeOf(value);
  const dynamic = schema.dynamic !== false;
  const modes: [string, string][] = [["value", "Wert"]];
  if (dynamic && schema.type === "number") modes.push(["audio", "Audio"], ["lfo", "LFO"]);
  if (dynamic && ["number", "color", "point"].includes(schema.type)) modes.push(["keys", "Keyframes"]);
  const d = (value ?? {}) as Dyn;
  const base = mode === "value" ? (value ?? schema.default) : schema.default;
  const isSet = value !== undefined;

  const setMode = (m: string) => {
    if (m === "value") onChange(typeof base === "object" ? schema.default : base);
    if (m === "audio") onChange({ audio: "low", min: schema.min ?? 0, max: Math.min(schema.max ?? 1, 1) });
    if (m === "lfo") onChange({ lfo: "sine", beats: 4, min: schema.min ?? 0, max: Math.min(schema.max ?? 1, 1) });
    if (m === "keys") onChange({ keys: [[0, base], [Math.max(1, round(clipTime)), base]], ease: "linear" });
  };

  return (
    <div className="param">
      <div className="row between" style={{ marginBottom: 4 }}>
        <span title={schema.description}>
          <code>{name}</code> <span className="unit">{schema.description}</span>
        </span>
        <div className="row" style={{ gap: 2, flexWrap: "nowrap" }}>
          {modes.length > 1 &&
            modes.map(([m, label]) => (
              <button key={m} className={`btn small${mode === m ? " active" : ""}`} style={{ padding: "1px 6px" }} onClick={() => setMode(m)}>
                {label}
              </button>
            ))}
          {isSet && (
            <button className="btn ghost small" style={{ padding: "1px 5px" }} title="auf Standard zurücksetzen" onClick={() => onChange(undefined)}>
              ↺
            </button>
          )}
        </div>
      </div>
      {mode === "value" && <ValueEditor schema={schema} value={value} onChange={onChange} palettes={palettes} />}
      {mode === "audio" && (
        <div className="dyn">
          <Field label="Quelle">
            <select value={String(d.audio)} onChange={(e) => onChange({ ...d, audio: e.target.value })}>
              {AUDIO.map((a) => (
                <option key={a} value={a}>
                  {AUDIO_LABEL[a]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="leise → laut">
            <div className="row" style={{ flexWrap: "nowrap" }}>
              <NumberInput value={Number(d.min ?? 0)} step={0.05} onChange={(v) => onChange({ ...d, min: v })} />
              <span className="unit">→</span>
              <NumberInput value={Number(d.max ?? 1)} step={0.05} onChange={(v) => onChange({ ...d, max: v })} />
            </div>
          </Field>
          <Field label="Kurve (pow)">
            <NumberInput value={Number(d.pow ?? 1)} min={0.1} max={8} step={0.1} onChange={(v) => onChange({ ...d, pow: v })} />
          </Field>
        </div>
      )}
      {mode === "lfo" && (
        <div className="dyn">
          <Field label="Form">
            <select value={String(d.lfo)} onChange={(e) => onChange({ ...d, lfo: e.target.value })}>
              {["sine", "triangle", "saw", "square"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </Field>
          <Field label="Periode (Beats)">
            <NumberInput value={Number(d.beats ?? 4)} min={0.25} max={64} step={0.25} onChange={(v) => onChange({ ...d, beats: v })} />
          </Field>
          <Field label="min → max">
            <div className="row" style={{ flexWrap: "nowrap" }}>
              <NumberInput value={Number(d.min ?? 0)} step={0.05} onChange={(v) => onChange({ ...d, min: v })} />
              <span className="unit">→</span>
              <NumberInput value={Number(d.max ?? 1)} step={0.05} onChange={(v) => onChange({ ...d, max: v })} />
            </div>
          </Field>
        </div>
      )}
      {mode === "keys" && (
        <div className="dyn">
          {(d.keys ?? []).map(([kt, kv], i) => (
            <div key={i} className="row" style={{ flexWrap: "nowrap", marginBottom: 4 }}>
              <div style={{ width: 64 }}>
                <NumberInput
                  value={Number(kt)}
                  min={0}
                  step={0.1}
                  title="Sekunden ab Clip-Start"
                  onChange={(v) => {
                    const keys = [...(d.keys ?? [])];
                    keys[i] = [v, kv];
                    onChange({ ...d, keys });
                  }}
                />
              </div>
              <div className="grow">
                <ValueEditor
                  schema={schema}
                  value={kv}
                  palettes={palettes}
                  onChange={(v) => {
                    const keys = [...(d.keys ?? [])];
                    keys[i] = [kt, v];
                    onChange({ ...d, keys });
                  }}
                />
              </div>
              <button
                className="btn ghost small"
                disabled={(d.keys ?? []).length <= 1}
                onClick={() => onChange({ ...d, keys: (d.keys ?? []).filter((_, j) => j !== i) })}
              >
                ×
              </button>
            </div>
          ))}
          <div className="row">
            <button
              className="btn small"
              onClick={() => {
                const keys = [...(d.keys ?? [])];
                const last = keys[keys.length - 1];
                keys.push([round(Math.max(clipTime, Number(last?.[0] ?? 0) + 1)), last?.[1] ?? schema.default]);
                onChange({ ...d, keys: keys.sort((a, b) => Number(a[0]) - Number(b[0])) });
              }}
            >
              + Keyframe (Playhead)
            </button>
            <select value={String(d.ease ?? "linear")} style={{ width: 110 }} onChange={(e) => onChange({ ...d, ease: e.target.value })}>
              <option value="linear">linear</option>
              <option value="smooth">weich</option>
              <option value="step">Sprung</option>
            </select>
          </div>
        </div>
      )}
    </div>
  );
}

function TargetEditor({ target, onChange }: { target: Target; onChange: (t: Target) => void }) {
  const project = useStore((s) => s.project)!;
  const tags = [...new Set(project.fixtures.flatMap((f) => f.tags))].sort();
  const all = !target.fixtures && !target.tags && !(target.where ?? []).length;
  const toggle = (key: "fixtures" | "tags", id: string) => {
    const cur = new Set(target[key] ?? []);
    if (cur.has(id)) cur.delete(id);
    else cur.add(id);
    const list = [...cur];
    onChange({ ...target, [key]: list.length ? list : null });
  };
  return (
    <div>
      <label className="row" style={{ marginBottom: 6 }}>
        <input type="checkbox" checked={all} onChange={(e) => e.target.checked && onChange({})} /> alle LEDs
      </label>
      <div className="unit" style={{ marginBottom: 2 }}>Strips</div>
      <div className="row" style={{ gap: 4, marginBottom: 6 }}>
        {project.fixtures.map((f) => (
          <button key={f.id} className={`btn small${target.fixtures?.includes(f.id) ? " active" : ""}`} onClick={() => toggle("fixtures", f.id)}>
            {f.name}
          </button>
        ))}
      </div>
      {tags.length > 0 && (
        <>
          <div className="unit" style={{ marginBottom: 2 }}>Tags</div>
          <div className="row" style={{ gap: 4, marginBottom: 6 }}>
            {tags.map((t) => (
              <button key={t} className={`btn small${target.tags?.includes(t) ? " active" : ""}`} onClick={() => toggle("tags", t)}>
                #{t}
              </button>
            ))}
          </div>
        </>
      )}
      <div className="unit" style={{ marginBottom: 2 }}>Bereich (UND-verknüpft)</div>
      {(target.where ?? []).map((w, i) => (
        <div key={i} className="row" style={{ flexWrap: "nowrap", marginBottom: 4 }}>
          <select
            value={w.field}
            style={{ width: 120 }}
            onChange={(e) => {
              const where = [...(target.where ?? [])];
              where[i] = { ...w, field: e.target.value };
              onChange({ ...target, where });
            }}
          >
            {["x", "y", "z", "nx", "ny", "nz", "u", "azimuth", "elevation", "distance"].map((f) => (
              <option key={f}>{f}</option>
            ))}
          </select>
          <input
            type="number"
            placeholder="min"
            value={w.min ?? ""}
            onChange={(e) => {
              const where = [...(target.where ?? [])];
              where[i] = { ...w, min: e.target.value === "" ? null : +e.target.value };
              onChange({ ...target, where });
            }}
          />
          <input
            type="number"
            placeholder="max"
            value={w.max ?? ""}
            onChange={(e) => {
              const where = [...(target.where ?? [])];
              where[i] = { ...w, max: e.target.value === "" ? null : +e.target.value };
              onChange({ ...target, where });
            }}
          />
          <button className="btn ghost small" onClick={() => onChange({ ...target, where: (target.where ?? []).filter((_, j) => j !== i) })}>
            ×
          </button>
        </div>
      ))}
      <div className="row">
        <button className="btn small" onClick={() => onChange({ ...target, where: [...(target.where ?? []), { field: "azimuth", min: -45, max: 45 }] })}>
          + Bereich
        </button>
        <label className="row unit">
          <input type="checkbox" checked={!!target.invert} onChange={(e) => onChange({ ...target, invert: e.target.checked })} /> umkehren
        </label>
      </div>
    </div>
  );
}

function ClipInspector({
  show,
  clip,
  layer,
  effects,
  shaders,
  palettes,
  apply,
  playhead,
  onLooksChanged,
}: {
  show: Show;
  clip: Clip;
  layer: Layer;
  effects: EffectInfo[];
  shaders: string[];
  palettes: Record<string, string[]>;
  apply: (fn: (s: Show) => Show) => void;
  playhead: number;
  onLooksChanged: () => void;
}) {
  const info = effects.find((e) => e.id === clip.effect);
  const set = (patch: Partial<Clip>) => apply((s) => updateClip(s, clip.id, patch));
  const setParam = (name: string, v: unknown | undefined) => {
    const params = { ...clip.params };
    if (v === undefined) delete params[name];
    else params[name] = v;
    set({ params });
  };
  const [raw, setRaw] = useState(false);
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setText(JSON.stringify(clip.params, null, 2));
    setErr(null);
  }, [clip]);

  return (
    <div>
      <div className="row between" style={{ marginBottom: 6 }}>
        <strong>{info?.name ?? clip.effect}</strong>
        <span className="unit">Ebene: {layer.name}</span>
      </div>
      {info && <p className="hint">{info.description}</p>}
      <Field label="Effekt">
        <select value={clip.effect} onChange={(e) => apply((s) => updateClip(s, clip.id, changeEffect(clip, e.target.value, effects)))}>
          {effects.map((e) => (
            <option key={e.id} value={e.id}>
              {e.name}
            </option>
          ))}
          {shaders.map((sh) => (
            <option key={sh} value={`shader:${sh}`}>
              ⚙ {sh}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Start / Ende (s)">
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <NumberInput value={clip.start} min={0} step={0.1} onChange={(v) => v < clip.end && set({ start: v })} />
          <NumberInput value={clip.end} min={0} step={0.1} onChange={(v) => v > clip.start && set({ end: v })} />
        </div>
      </Field>
      <Field label="Mischung">
        <select value={clip.blend} onChange={(e) => set({ blend: e.target.value })}>
          {BLENDS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </Field>
      <Field label={`Deckkraft ${Math.round(clip.opacity * 100)} %`}>
        <input type="range" min={0} max={1} step={0.01} value={clip.opacity} onChange={(e) => set({ opacity: +e.target.value })} />
      </Field>
      <Field label="Ein- / Ausblenden (s)">
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <NumberInput value={clip.fade_in} min={0} step={0.1} onChange={(v) => set({ fade_in: v })} />
          <NumberInput value={clip.fade_out} min={0} step={0.1} onChange={(v) => set({ fade_out: v })} />
        </div>
      </Field>

      <div className="row between">
        <h3 style={{ margin: "14px 0 8px" }}>Parameter</h3>
        <button className="btn ghost small" onClick={() => setRaw((r) => !r)}>
          {raw || !info ? "Formular" : "JSON"}
        </button>
      </div>
      {info && !raw ? (
        Object.entries(info.params).map(([name, schema]) => (
          <ParamControl
            key={name}
            name={name}
            schema={schema}
            value={clip.params[name]}
            palettes={palettes}
            clipTime={Math.max(0, playhead - clip.start)}
            onChange={(v) => setParam(name, v)}
          />
        ))
      ) : (
        <>
          <textarea rows={8} value={text} spellCheck={false} onChange={(e) => setText(e.target.value)} />
          {err && <div className="banner err">{err}</div>}
          <button
            className="btn small"
            onClick={() => {
              try {
                set({ params: JSON.parse(text) });
                setErr(null);
              } catch (e) {
                setErr((e as Error).message);
              }
            }}
          >
            Parameter übernehmen
          </button>
        </>
      )}

      <h3 style={{ margin: "14px 0 8px" }}>Ziel</h3>
      <TargetEditor target={clip.target} onChange={(target) => set({ target })} />
      <div className="row between" style={{ marginTop: 14 }}>
        <SaveLookButton ids={new Set([clip.id])} showId={show.id} onSaved={onLooksChanged} />
        <button className="btn danger small" onClick={() => apply((s) => deleteClips(s, new Set([clip.id])))}>
          Clip löschen
        </button>
      </div>
      {show.layers.length === 0 && null}
    </div>
  );
}

function LayerInspector({ layer, apply, onDeleted }: { layer: Layer; apply: (fn: (s: Show) => Show) => void; onDeleted: () => void }) {
  return (
    <div>
      <strong>Ebene „{layer.name}"</strong>
      <p className="hint">Ebenen werden von unten nach oben übereinander gelegt; die oberste Zeile der Timeline liegt oben.</p>
      <Field label="Name">
        <input type="text" defaultValue={layer.name} key={layer.id + layer.name} onBlur={(e) => e.target.value.trim() && apply((s) => updateLayer(s, layer.id, { name: e.target.value.trim() }))} />
      </Field>
      <Field label="Sichtbar">
        <input type="checkbox" checked={layer.enabled} onChange={(e) => apply((s) => updateLayer(s, layer.id, { enabled: e.target.checked }))} />
      </Field>
      <Field label={`Deckkraft ${Math.round(layer.opacity * 100)} %`}>
        <input type="range" min={0} max={1} step={0.01} value={layer.opacity} onChange={(e) => apply((s) => updateLayer(s, layer.id, { opacity: +e.target.value }))} />
      </Field>
      <div className="row">
        <button className="btn small" onClick={() => apply((s) => moveLayer(s, layer.id, 1))}>
          ↑ nach oben
        </button>
        <button className="btn small" onClick={() => apply((s) => moveLayer(s, layer.id, -1))}>
          ↓ nach unten
        </button>
        <button
          className="btn danger small"
          onClick={() => {
            if (layer.clips.length && !confirm(`Ebene „${layer.name}" mit ${layer.clips.length} Clips löschen?`)) return;
            apply((s) => deleteLayer(s, layer.id));
            onDeleted();
          }}
        >
          Ebene löschen
        </button>
      </div>
    </div>
  );
}

function SaveLookButton({ ids, showId, onSaved }: { ids: Set<string>; showId: string; onSaved: () => void }) {
  const slug = useStore((s) => s.slug)!;
  const notify = useStore((s) => s.notify);
  return (
    <button
      className="btn small"
      title="Auswahl als wiederverwendbaren Look speichern (Zeiten in Beats)"
      onClick={async () => {
        const name = prompt("Name des Looks", "Mein Look");
        if (!name) return;
        try {
          await api.createLook(slug, { name, show_id: showId, clip_ids: [...ids] });
          notify(`Look „${name}“ gespeichert`, "success");
          onSaved();
        } catch (e) {
          notify((e as Error).message, "error");
        }
      }}
    >
      ✦ Als Look speichern
    </button>
  );
}

function LookManager({ looks, onChanged }: { looks: Look[]; onChanged: () => void }) {
  const slug = useStore((s) => s.slug)!;
  const own = looks.filter((l) => !l.builtin);
  return (
    <div>
      <h3>Eigene Looks</h3>
      {own.length === 0 && <p className="hint">Noch keine. Clips auswählen und „Als Look speichern“.</p>}
      <div className="list">
        {own.map((l) => (
          <div key={l.id} className="list-item" style={{ cursor: "default" }}>
            <span className="grow">
              ✦ {l.name} <span className="unit">· {l.beats} Beats</span>
            </span>
            <button
              className="btn ghost small"
              onClick={async () => {
                if (!confirm(`Look „${l.name}“ löschen?`)) return;
                await api.deleteLook(slug, l.id);
                onChanged();
              }}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function MultiInspector({ ids, apply, showId, onLooksChanged }: { ids: Set<string>; apply: (fn: (s: Show) => Show) => void; showId: string; onLooksChanged: () => void }) {
  return (
    <div>
      <div className="row between">
        <strong>{ids.size} Clips ausgewählt</strong>
        <SaveLookButton ids={ids} showId={showId} onSaved={onLooksChanged} />
      </div>
      <p className="hint">Gemeinsam verschieben per Ziehen; Strg+C / Strg+V kopiert sie an den Playhead.</p>
      <Field label="Deckkraft">
        <input type="range" min={0} max={1} step={0.01} defaultValue={1} onChange={(e) => apply((s) => mapClips(s, ids, (c) => ({ ...c, opacity: +e.target.value })))} />
      </Field>
      <Field label="Mischung">
        <select defaultValue="" onChange={(e) => e.target.value && apply((s) => mapClips(s, ids, (c) => ({ ...c, blend: e.target.value })))}>
          <option value="">–</option>
          {BLENDS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </Field>
      <button className="btn danger small" onClick={() => apply((s) => deleteClips(s, ids))}>
        {ids.size} Clips löschen
      </button>
    </div>
  );
}

export function Inspector(props: {
  show: Show;
  selection: Set<string>;
  selectedLayer: string | null;
  setSelectedLayer: (id: string | null) => void;
  effects: EffectInfo[];
  shaders: string[];
  palettes: Record<string, string[]>;
  apply: (fn: (s: Show) => Show) => void;
  playhead: number;
  looks: Look[];
  onLooksChanged: () => void;
}) {
  const { show, selection, selectedLayer } = props;
  if (selection.size > 1) return <MultiInspector ids={selection} apply={props.apply} showId={show.id} onLooksChanged={props.onLooksChanged} />;
  if (selection.size === 1) {
    const found = findClip(show, [...selection][0]);
    if (found) return <ClipInspector {...props} clip={found.clip} layer={found.layer} />;
  }
  const layer = show.layers.find((l) => l.id === selectedLayer);
  if (layer) return <LayerInspector layer={layer} apply={props.apply} onDeleted={() => props.setSelectedLayer(null)} />;
  return (
    <div className="hint">
      <p>Clip oder Ebene in der Timeline anklicken.</p>
      <ul style={{ paddingLeft: 18, lineHeight: 1.7 }}>
        <li>Effekt aus der Leiste in eine Ebene ziehen</li>
        <li>Doppelklick in eine Ebene: Clip mit gewähltem Effekt</li>
        <li>Clip ziehen: verschieben (auch in andere Ebenen)</li>
        <li>Clip-Ränder ziehen: kürzen / verlängern</li>
        <li>Einrasten an Beats/Takten, Alt: frei</li>
        <li>Strg/Shift-Klick: Mehrfachauswahl</li>
        <li>Strg+Z / Strg+Y: rückgängig / wiederholen</li>
        <li>Strg+C / Strg+V / Strg+D, Entf</li>
        <li>✦ Looks aus der Leiste ziehen; Auswahl als Look speichern</li>
      </ul>
      <LookManager looks={props.looks} onChanged={props.onLooksChanged} />
    </div>
  );
}
