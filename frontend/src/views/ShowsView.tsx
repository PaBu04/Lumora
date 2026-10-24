import { Panes } from "../components/Panes";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { SERIES } from "../calibration";
import { LineChart } from "../components/LineChart";
import { Versions } from "../components/Versions";
import { Waveform } from "../components/Waveform";
import { useStore } from "../store";
import { Scene3D } from "../three/Scene3D";
import { Inspector } from "../editor/Inspector";
import { allClips, deleteClips, insertLookClips, moveClips, pasteClips, type SnapMode } from "../editor/ops";
import { CuePads } from "../editor/CuePads";
import { EffectBar, TimelineEditor, usePlayhead } from "../editor/TimelineEditor";
import { useShowEditor } from "../editor/useShowEditor";
import type { Analysis, Clip, EffectInfo, Issue, Look, PowerReport, Show, StarterStyle } from "../types";
import { EmptyState, Field, formatTime, Icon, Modal, useContextMenu } from "../ui";
import { moveItem } from "../geometry";
import { AiGenerator } from "./AiView";
import { Help } from "../components/Help";

const STYLES: { value: StarterStyle["style"]; label: string; hint: string }[] = [
  { value: "party", label: "Party", hint: "viel Schlagzeug, Akzente und Cues, Glitzer auf dem Höhepunkt" },
  { value: "calm", label: "Ruhig", hint: "weiche Übergänge, wenig Akzente, Raumfarbe folgt den Akkorden" },
  { value: "cinematic", label: "Kino", hint: "großer Bogen: Gesten auf Phrasen und Motiven, starker Hell-Dunkel-Kontrast" },
  { value: "minimal", label: "Minimal", hint: "nur Schlagzeug und Melodie auf wenigen Strips" },
];
const COLORS: { value: StarterStyle["colors"]; label: string }[] = [
  { value: "auto", label: "automatisch (nach Tonart)" },
  { value: "cool", label: "kühl" },
  { value: "warm", label: "warm" },
  { value: "neon", label: "Neon" },
  { value: "nature", label: "Natur" },
  { value: "mono", label: "monochrom" },
];

function NewShowForm({ onCreated, onClose }: { onCreated: (id: string) => void; onClose: () => void }) {
  const slug = useStore((s) => s.slug)!;
  const songs = useStore((s) => s.songs);
  const refreshShows = useStore((s) => s.refreshShows);
  const notify = useStore((s) => s.notify);
  const [name, setName] = useState("");
  const [song, setSong] = useState("");
  const [template, setTemplate] = useState("starter");
  const [style, setStyle] = useState<StarterStyle>({ style: "party", colors: "auto", brightness: 1, strobe: false, variant: 0 });
  const songId = song || songs[0]?.id || "";
  const chosen = STYLES.find((s) => s.value === style.style)!;
  return (
    <div className="card">
      <div>
        <Field label="Name" stack>
          <input type="text" value={name} placeholder="z. B. Party-Show" onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Song" stack>
          <select value={songId} onChange={(e) => setSong(e.target.value)}>
            {songs.length === 0 && <option value="">(kein Song – erst unter „Songs" hochladen)</option>}
            {songs.map((s) => (
              <option key={s.id} value={s.id}>
                {s.artist ? `${s.artist} – ` : ""}
                {s.title}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Vorlage" stack>
          <select value={template} onChange={(e) => setTemplate(e.target.value)}>
            <option value="starter">Starter-Show (aus Songstruktur)</option>
            <option value="empty">Leer (z. B. für die KI)</option>
          </select>
        </Field>
        {template === "starter" && (
          <>
            <Field label="Stil" stack help={<Help id="styles" />}>
              <div className="style-grid" role="group" aria-label="Stil">
                {STYLES.map((s) => (
                  <button
                    key={s.value}
                    className={`btn small${style.style === s.value ? " active" : ""}`}
                    title={s.hint}
                    onClick={() => setStyle({ ...style, style: s.value })}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </Field>
            <p className="hint" style={{ margin: "-4px 0 8px" }}>
              {chosen.hint}
            </p>
            <Field label="Farben" stack>
              <select value={style.colors} onChange={(e) => setStyle({ ...style, colors: e.target.value as StarterStyle["colors"] })}>
                {COLORS.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={`Grundhelligkeit ${Math.round(style.brightness * 100)} %`} stack>
              <input
                type="range"
                min={0.5}
                max={1.3}
                step={0.05}
                value={style.brightness}
                onChange={(e) => setStyle({ ...style, brightness: +e.target.value })}
              />
            </Field>
            <label className="check-line">
              <input type="checkbox" checked={style.strobe} onChange={(e) => setStyle({ ...style, strobe: e.target.checked })} />
              Stroboskop auf dem Höhepunkt erlauben
            </label>
          </>
        )}
        <button
          className="btn primary"
          style={{ width: "100%" }}
          onClick={async () => {
            try {
              const show = await api.createShow(slug, name.trim() || "Neue Show", songId || null, template, style);
              await refreshShows();
              onCreated(show.id);
              setName("");
              onClose();
              notify(`Show „${show.name}" erstellt`, "success");
            } catch (e) {
              notify((e as Error).message, "error");
            }
          }}
        >
          Erstellen
        </button>
      </div>
    </div>
  );
}

function Transport({ duration, analysis }: { duration: number; analysis: Analysis | null }) {
  const pb = useStore((s) => s.playback);
  const setPlayback = useStore((s) => s.setPlayback);
  const t = usePlayhead();
  if (!pb) return null;
  return (
    <div className="transport">
      <button className="btn icon" title="Abspielen / Pause (Leertaste)" disabled={!pb.show} onClick={async () => setPlayback(await (pb.playing ? api.pause() : api.play()))}>
        <Icon name={pb.playing ? "pause" : "play"} />
      </button>
      <button className="btn icon" title="Stopp" disabled={!pb.show} onClick={async () => setPlayback(await api.stop())}>
        <Icon name="stop" />
      </button>
      <span className="time">
        {pb.live_input ? `Live · ${pb.live_input.bpm.toFixed(0)} BPM` : `${formatTime(t)} / ${formatTime(duration)}`}
      </span>
      <div className="seekbar">
        <Waveform analysis={analysis} duration={duration} position={t} onSeek={async (s) => setPlayback(await api.seek(s))} />
      </div>
    </div>
  );
}

function JsonPanel({ show, onSave }: { show: Show; onSave: (s: Show) => Promise<void> }) {
  const [text, setText] = useState(() => JSON.stringify(show, null, 2));
  const [dirty, setDirty] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!dirty) setText(JSON.stringify(show, null, 2));
  }, [show, dirty]);
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <textarea
        style={{ flex: 1, minHeight: 300 }}
        value={text}
        spellCheck={false}
        onChange={(e) => {
          setText(e.target.value);
          setDirty(true);
        }}
      />
      {err && <div className="banner err">{err}</div>}
      <div className="row" style={{ marginTop: 6 }}>
        <button
          className="btn primary small"
          disabled={!dirty}
          onClick={async () => {
            try {
              await onSave(JSON.parse(text));
              setDirty(false);
              setErr(null);
            } catch (e) {
              setErr((e as Error).message);
            }
          }}
        >
          Speichern
        </button>
        <button className="btn small" disabled={!dirty} onClick={() => setDirty(false)}>
          Verwerfen
        </button>
      </div>
    </div>
  );
}

function PowerChart({ slug, show }: { slug: string; show: Show }) {
  const [report, setReport] = useState<PowerReport | null>(null);
  const project = useStore((s) => s.project);
  const rev = useStore((s) => s.showRevision);
  useEffect(() => {
    setReport(null);
    if (project?.controllers.length) api.power(slug, show.id, 2).then(setReport).catch(() => setReport(null));
  }, [slug, show, rev, project?.controllers.length]);
  if (!project?.controllers.length) return null;
  if (!report) return <p className="hint">Berechne Stromverlauf…</p>;
  const ids = Object.keys(report.controllers);
  const budgets = ids.filter((id) => report.controllers[id].budget_ma).slice(0, 4);
  return (
    <div className="card">
      <strong>Stromverlauf (vor Drosselung)</strong>
      <div className="row" style={{ margin: "6px 0" }}>
        {ids.map((id) => {
          const c = report.controllers[id];
          const over = c.budget_ma && c.peak_ma > c.budget_ma;
          return (
            <span key={id} className={`badge ${over ? "warn" : ""}`}>
              {c.name}: max {(c.peak_ma / 1000).toFixed(1)} A{c.budget_ma ? ` / ${(c.budget_ma / 1000).toFixed(1)} A` : ""}
            </span>
          );
        })}
      </div>
      <LineChart
        x={report.times}
        series={ids.slice(0, 8).map((id, i) => ({ name: report.controllers[id].name, color: SERIES[i], values: report.curves[id].map((v) => v / 1000) }))}
        refLines={budgets.map((id) => ({ y: report.controllers[id].budget_ma! / 1000, label: `Budget ${report.controllers[id].name}`, color: "#d03b3b" }))}
        height={150}
        xFormat={(v) => formatTime(v)}
        yFormat={(v) => `${v.toFixed(1)} A`}
      />
    </div>
  );
}

function IssuesPanel({ slug, show }: { slug: string; show: Show }) {
  const [issues, setIssues] = useState<Issue[] | null>(null);
  const rev = useStore((s) => s.showRevision);
  useEffect(() => {
    setIssues(null);
    api.validate(slug, show.id).then(setIssues);
  }, [slug, show, rev]);
  if (!issues) return <p className="hint">Prüfe…</p>;
  if (issues.length === 0)
    return (
      <>
        <PowerChart slug={slug} show={show} />
        <div className="banner info">Keine Probleme gefunden.</div>
      </>
    );
  return (
    <div className="list">
      <PowerChart slug={slug} show={show} />
      {issues.map((i, k) => (
        <div key={k} className="card" style={{ marginBottom: 0 }}>
          <span className={`badge ${i.severity === "error" ? "err" : "warn"}`}>{i.severity === "error" ? "Fehler" : "Hinweis"}</span>{" "}
          {(i.layer || i.clip) && (
            <span className="unit">
              {i.layer} / {i.clip}
            </span>
          )}
          <div style={{ marginTop: 4 }}>{i.message}</div>
        </div>
      ))}
    </div>
  );
}

function IsolationToggle() {
  const [on, setOn] = useState<boolean | null>(null);
  useEffect(() => {
    api.settings().then((s) => setOn(s.shader_isolation));
  }, []);
  if (on === null) return null;
  return (
    <label className="row unit" style={{ marginBottom: 8 }} title="Hängende oder abstürzende Shader werden gestoppt, ohne die App zu beeinträchtigen">
      <input type="checkbox" checked={on} onChange={async (e) => setOn((await api.saveSettings({ shader_isolation: e.target.checked })).shader_isolation)} />
      Shader in eigenem Prozess ausführen (empfohlen)
    </label>
  );
}

function ShaderPanel({ slug }: { slug: string }) {
  const [list, setList] = useState<{ shaders: string[]; errors: Record<string, string>; api: string } | null>(null);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const notify = useStore((s) => s.notify);
  const rev = useStore((s) => s.showRevision);
  useEffect(() => {
    api.shaders(slug).then(setList);
  }, [slug, rev]);
  const open = async (n: string) => {
    setName(n);
    setCode(await api.shader(slug, n));
    setErr(null);
  };
  return (
    <div>
      <p className="hint">Eigene Effekte in Python/numpy. In Clips als Effekt „shader:&lt;name&gt;" verwenden.</p>
      <IsolationToggle />
      <div className="row" style={{ marginBottom: 8 }}>
        {list?.shaders.map((s) => (
          <button key={s} className={`btn small${s === name ? " active" : ""}`} onClick={() => open(s)}>
            {s}
            {list.errors[s] && " ⚠"}
          </button>
        ))}
        <button
          className="btn small"
          onClick={() => {
            setName("mein_effekt");
            setCode("def render(t, leds, audio, params):\n    hue = leds.coord('azimuth') + t * 0.1\n    return hsv(hue, 1.0, 0.3 + 0.7 * audio.low)\n");
          }}
        >
          <Icon name="plus" /> Neu
        </button>
      </div>
      {name && (
        <>
          <Field label="Name">
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <textarea rows={14} value={code} spellCheck={false} onChange={(e) => setCode(e.target.value)} />
          {err && <div className="banner err">{err}</div>}
          <div className="row" style={{ marginTop: 6 }}>
            <button
              className="btn primary small"
              onClick={async () => {
                try {
                  await api.saveShader(slug, name, code);
                  setErr(null);
                  notify(`Shader „${name}" gespeichert`, "success");
                  setList(await api.shaders(slug));
                } catch (e) {
                  setErr((e as Error).message);
                }
              }}
            >
              Speichern
            </button>
            <button
              className="btn danger small"
              onClick={async () => {
                await api.deleteShader(slug, name).catch(() => undefined);
                setName("");
                setList(await api.shaders(slug));
              }}
            >
              Löschen
            </button>
          </div>
        </>
      )}
      {list && (
        <details style={{ marginTop: 12 }}>
          <summary className="unit">Shader-API</summary>
          <pre className="code">{list.api}</pre>
        </details>
      )}
    </div>
  );
}

let clipboard: { clip: Clip; li: number }[] = [];

function LiveInputCard() {
  const pb = useStore((s) => s.playback);
  const setPlayback = useStore((s) => s.setPlayback);
  const notify = useStore((s) => s.notify);
  const [devices, setDevices] = useState<{ index: number | string; name: string; default: boolean; kind: string }[] | null>(null);
  const [device, setDevice] = useState<string>("");
  const [starting, setStarting] = useState(false);
  const live = pb?.live_input;
  useEffect(() => {
    api
      .liveDevices()
      .then((d) => {
        setDevices(d);
        const desktop = d.find((x) => x.kind === "desktop");
        if (desktop) setDevice(String(desktop.index)); // what the PC plays is the usual source
      })
      .catch(() => setDevices([]));
  }, []);
  const desktop = devices?.filter((d) => d.kind === "desktop") ?? [];
  const inputs = devices?.filter((d) => d.kind !== "desktop") ?? [];
  return (
    <div className={`card${live ? " selected" : ""}`}>
      <div className="row between">
        <strong>
          Live-Eingang <Help id="liveinput" />
        </strong>
        {live && <span className="badge ok">{live.bpm.toFixed(0)} BPM</span>}
      </div>
      <p className="hint">Reagiert in Echtzeit auf Musik vom PC (Browser, Spotify …) oder ein Mikrofon.</p>
      {live ? (
        <>
          <div className="unit" title={live.device} style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginBottom: 6 }}>
            {live.device}
          </div>
          {(["low", "mid", "high"] as const).map((k) => (
            <div key={k} className="row" style={{ flexWrap: "nowrap", marginBottom: 3 }}>
              <span className="unit" style={{ width: 48 }}>{k === "low" ? "Bass" : k === "mid" ? "Mitten" : "Höhen"}</span>
              <div className="meter">
                <div style={{ width: `${Math.round((live.levels[k] ?? 0) * 100)}%` }} />
              </div>
            </div>
          ))}
          <button className="btn small" style={{ marginTop: 6 }} onClick={async () => setPlayback(await api.liveInput(false))}>
            Beenden
          </button>
        </>
      ) : devices && devices.length === 0 ? (
        <span className="unit">Keine Audioquelle gefunden.</span>
      ) : (
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <select value={device} onChange={(e) => setDevice(e.target.value)} title="Audioquelle">
            {desktop.length > 0 && (
              <optgroup label="Was der PC abspielt">
                {desktop.map((d) => (
                  <option key={d.index} value={String(d.index)}>
                    {d.name}
                  </option>
                ))}
              </optgroup>
            )}
            <optgroup label="Mikrofon / Line-In">
              <option value="">Standard-Eingang</option>
              {inputs.map((d) => (
                <option key={d.index} value={String(d.index)}>
                  {d.name}
                </option>
              ))}
            </optgroup>
          </select>
          <button
            className="btn small"
            disabled={starting}
            onClick={async () => {
              setStarting(true);
              try {
                setPlayback(await api.liveInput(true, null, device === "" ? null : /^\d+$/.test(device) ? +device : device));
              } catch (e) {
                notify((e as Error).message, "error");
              } finally {
                setStarting(false);
              }
            }}
          >
            {starting ? "…" : "Starten"}
          </button>
        </div>
      )}
    </div>
  );
}

function ExportCard({ slug, showId }: { slug: string; showId: string }) {
  const [fps, setFps] = useState(40);
  const project = useStore((s) => s.project);
  const ready = (project?.controllers.length ?? 0) > 0;
  return (
    <div className="card">
      <strong>
        Exportieren <Help id="export" />
      </strong>
      <p className="hint">Für xLights oder einen Falcon Player – die Show läuft dann ohne PC.</p>
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <select value={fps} onChange={(e) => setFps(+e.target.value)} style={{ width: 90 }}>
          {[20, 25, 40, 50].map((f) => (
            <option key={f} value={f}>
              {f} FPS
            </option>
          ))}
        </select>
        {ready ? (
          <a className="btn small" href={`/api/projects/${slug}/shows/${showId}/export?fps=${fps}`} download>
            Exportieren
          </a>
        ) : (
          <span className="unit">erst Controller anlegen</span>
        )}
      </div>
    </div>
  );
}

export function ShowsView() {
  const slug = useStore((s) => s.slug);
  const shows = useStore((s) => s.shows);
  const songs = useStore((s) => s.songs);
  const pb = useStore((s) => s.playback);
  const setPlayback = useStore((s) => s.setPlayback);
  const refreshShows = useStore((s) => s.refreshShows);
  const setUndoScope = useStore((s) => s.setUndoScope);
  const notify = useStore((s) => s.notify);
  const currentId = pb?.project === slug && pb?.show !== "__sync__" ? (pb?.show ?? null) : null;
  const editor = useShowEditor(slug, currentId);
  const { show, apply } = editor;
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [selectedLayer, setSelectedLayer] = useState<string | null>(null);
  const [panel, setPanel] = useState<"edit" | "json" | "issues" | "history" | "shader">("edit");
  const expert = useStore((s) => s.expert);
  const [viewerCam, setViewerCam] = useState(false);
  const [effects, setEffects] = useState<EffectInfo[]>([]);
  const [palettes, setPalettes] = useState<Record<string, string[]>>({});
  const [shaders, setShaders] = useState<string[]>([]);
  const [snapMode, setSnapMode] = useState<SnapMode>("beat");
  const [zoom, setZoom] = useState(1);
  const [pick, setPick] = useState("pulse");
  const [creating, setCreating] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const aiRun = useStore((s) => s.aiRun);
  const [drag, setDrag] = useState<{ from: number; over: number } | null>(null);
  const ctx = useContextMenu();
  const bumpShowRevision = useStore((s) => s.bumpShowRevision);
  const [looks, setLooks] = useState<Look[]>([]);
  const refreshLooks = useCallback(() => {
    if (slug) api.looks(slug).then(setLooks);
  }, [slug]);
  useEffect(refreshLooks, [refreshLooks]);
  const rev = useStore((s) => s.showRevision);
  const playhead = usePlayhead();

  useEffect(() => {
    api.effects().then((r) => {
      setEffects(r.effects);
      setPalettes(r.palettes);
    });
  }, []);
  useEffect(() => {
    if (slug) api.shaders(slug).then((r) => setShaders(Object.keys(r.errors).length ? r.shaders.filter((s) => !r.errors[s]) : r.shaders));
  }, [slug, rev]);
  useEffect(() => {
    setUndoScope("show");
    return () => setUndoScope("project");
  }, [setUndoScope]);

  const song = songs.find((s) => s.id === show?.song_id);
  useEffect(() => {
    setAnalysis(null);
    if (song?.status === "done") api.analysis(song.id).then(setAnalysis);
  }, [song?.id, song?.status, rev]);

  const open = useCallback(
    async (id: string) => {
      if (!slug) return;
      setPlayback(await api.load(slug, id));
      setSelection(new Set());
      setSelectedLayer(null);
    },
    [slug, setPlayback],
  );

  const duration = pb?.duration || analysis?.duration || show?.duration || 0;
  const errors = useMemo(() => pb?.clip_errors ?? {}, [pb?.clip_errors]);

  // keyboard: transport, undo/redo and clip editing
  useEffect(() => {
    const onKey = async (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select")) return;
      const ctrl = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();
      if (e.code === "Space") {
        e.preventDefault();
        const st = useStore.getState().playback;
        if (st?.show) setPlayback(await (st.playing ? api.pause() : api.play()));
        return;
      }
      if (!show) return;
      if (ctrl && key === "z" && !e.shiftKey) {
        e.preventDefault();
        editor.undo();
      } else if (ctrl && (key === "y" || (key === "z" && e.shiftKey))) {
        e.preventDefault();
        editor.redo();
      } else if ((key === "delete" || key === "backspace") && selection.size) {
        e.preventDefault();
        apply((s) => deleteClips(s, selection));
        setSelection(new Set());
      } else if (ctrl && key === "c" && selection.size) {
        clipboard = allClips(show).filter((c) => selection.has(c.clip.id)).map(({ clip, li }) => ({ clip: structuredClone(clip), li }));
        notify(`${clipboard.length} Clip(s) kopiert`);
      } else if (ctrl && key === "v" && clipboard.length) {
        e.preventDefault();
        const t = useStore.getState().playback?.position ?? 0;
        let ids: string[] = [];
        apply((s) => {
          const r = pasteClips(s, clipboard, t, duration || 1e9);
          ids = r.ids;
          return r.show;
        });
        setSelection(new Set(ids));
      } else if (ctrl && key === "d" && selection.size) {
        e.preventDefault();
        const sel = allClips(show).filter((c) => selection.has(c.clip.id));
        const end = Math.max(...sel.map((c) => c.clip.end));
        let ids: string[] = [];
        apply((s) => {
          const r = pasteClips(s, sel, end, duration || 1e9);
          ids = r.ids;
          return r.show;
        });
        setSelection(new Set(ids));
      } else if (ctrl && key === "a") {
        e.preventDefault();
        setSelection(new Set(allClips(show).map((c) => c.clip.id)));
      } else if (key === "escape") {
        setSelection(new Set());
      } else if ((key === "arrowleft" || key === "arrowright") && selection.size) {
        e.preventDefault();
        const beat = analysis?.bpm ? 60 / analysis.bpm : 0.5;
        const step = (e.shiftKey ? 4 * beat : beat) * (key === "arrowleft" ? -1 : 1);
        apply((s) => moveClips(s, selection, step, 0, duration || 1e9));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [show, selection, apply, editor, duration, analysis, notify, setPlayback]);

  if (!slug) return null;

  const reorder = async (from: number, to: number) => {
    const next = moveItem(shows, from, to);
    useStore.setState({ shows: next });
    try {
      useStore.setState({ shows: await api.orderShows(slug, next.map((x) => x.id)) });
    } catch (e) {
      notify((e as Error).message, "error");
      await refreshShows();
    }
  };
  const rename = async (id: string, current: string) => {
    const name = prompt("Neuer Name der Show", current)?.trim();
    if (!name || name === current) return;
    try {
      const full = await api.show(slug, id);
      await api.saveShow(slug, { ...full, name });
      await refreshShows();
      bumpShowRevision();
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };
  const remove = async (id: string, name: string) => {
    if (!confirm(`Show „${name}“ löschen?`)) return;
    try {
      await api.deleteShow(slug, id);
      if (currentId === id) setPlayback(await api.load(slug, null));
      await refreshShows();
      notify(`Show „${name}“ gelöscht`);
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };
  const defaultEffect = effects.find((e) => e.id === pick) ?? { id: pick };

  return (
    <Panes id="shows" sizes={[240, null, 380]} className="view">
      <div className="pane">
        <h2>Shows</h2>
        <div className="row" style={{ marginBottom: 12, flexWrap: "nowrap" }}>
          <button className={`btn small grow${creating ? " active" : " primary"}`} onClick={() => setCreating(!creating)}>
            {creating ? "Abbrechen" : "+ Neue Show"}
          </button>
          <button
            className={`btn small grow${aiRun?.status === "running" ? " active" : ""}`}
            title="Show von Claude erstellen lassen (dein Claude-Abo, keine API-Kosten)"
            onClick={() => setAiOpen(true)}
          >
            <Icon name="spark" /> {aiRun?.status === "running" ? "KI arbeitet…" : "Mit KI"}
          </button>
        </div>
        {aiOpen && (
          <Modal title="Show mit KI erstellen" onClose={() => setAiOpen(false)} width={820}>
            <AiGenerator onOpenShow={() => setAiOpen(false)} />
          </Modal>
        )}
        {creating && <NewShowForm onCreated={open} onClose={() => setCreating(false)} />}
        <LiveInputCard />
        {show && <ExportCard slug={slug} showId={show.id} />}
        <h3>Deine Shows</h3>
        <div className="list" style={{ marginBottom: 8 }}>
          {shows.length === 0 &&
            (songs.some((s) => s.status === "done") ? (
              <EmptyState
                title="Noch keine Show"
                actions={
                  <>
                    <button className="btn primary small" onClick={() => setCreating(true)}>
                      + Neue Show
                    </button>
                    <button className="btn small" onClick={() => setAiOpen(true)}>
                      Mit KI
                    </button>
                  </>
                }
              >
                Eine Starter-Show folgt der Musik: wähle Song und Stil. Oder beschreibe der KI, wie die Show wirken soll.
              </EmptyState>
            ) : (
              <EmptyState
                title="Erst einen Song hochladen"
                actions={
                  <button className="btn primary small" onClick={() => useStore.getState().setTab("songs")}>
                    Zu „Songs“
                  </button>
                }
              >
                Jede Show gehört zu einem Song. Sobald einer analysiert ist, kannst du hier eine Show erstellen.
              </EmptyState>
            ))}
          {shows.map((s, i) => {
            const sg = songs.find((x) => x.id === s.song_id);
            const dropCls = drag && drag.over === i && drag.from !== i ? (drag.from < i ? " drop-below" : " drop-above") : "";
            return (
              <div
                key={s.id}
                className={`list-item${currentId === s.id ? " active" : ""}${dropCls}${drag?.from === i ? " dragging" : ""}`}
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.effectAllowed = "move";
                  e.dataTransfer.setData("text/plain", s.id);
                  setDrag({ from: i, over: i });
                }}
                onDragOver={(e) => {
                  if (!drag) return;
                  e.preventDefault();
                  if (drag.over !== i) setDrag({ ...drag, over: i });
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  if (drag && drag.from !== i) void reorder(drag.from, i);
                  setDrag(null);
                }}
                onDragEnd={() => setDrag(null)}
                onClick={() => open(s.id)}
                onContextMenu={(e) =>
                  ctx.open(e, [
                    ...(s.style && s.song_id
                      ? [
                          {
                            label: "Neue Variante würfeln",
                            onClick: async () => {
                              try {
                                const v = await api.showVariant(slug, s.id);
                                await refreshShows();
                                await open(v.id);
                                notify(`„${v.name}" erstellt`, "success");
                              } catch (err) {
                                notify((err as Error).message, "error");
                              }
                            },
                          },
                        ]
                      : []),
                    { label: "Umbenennen", onClick: () => void rename(s.id, s.name) },
                    { label: "Löschen", danger: true, onClick: () => void remove(s.id, s.name) },
                  ])
                }
              >
                <Icon name="show" />
                <div className="grow">
                  <div>{s.name}</div>
                  <div className="meta">
                    {sg ? sg.title : "ohne Song"} · {s.clips} Clips
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        {shows.length > 1 && <p className="hint">Ziehen zum Sortieren · Rechtsklick zum Umbenennen oder Löschen</p>}
        {ctx.menu}
      </div>

      <Panes id="shows-mid" dir="col" sizes={[null, 320]} min={120}>
        <div style={{ position: "relative" }}>
          <div className="canvas-wrap">
            <Scene3D viewerCam={viewerCam} />
          </div>
          <div className="overlay">
            <span className="badge">{show ? show.name : "Keine Show geladen"}</span>
            {Object.keys(errors).length > 0 && <span className="badge err">{Object.keys(errors).length} Clip-Fehler</span>}
          </div>
          <div className="overlay right">
            <button className={`btn small${viewerCam ? " active" : ""}`} onClick={() => setViewerCam((v) => !v)}>
              {viewerCam ? "Freie Kamera" : "Betrachter-Sicht"}
            </button>
          </div>
        </div>
        <div className="player-area">
        <Transport duration={duration} analysis={analysis} />
        {show ? (
          <div className="editor-toolbar">
            <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
              <button className="btn ghost small" title="Rückgängig (Strg+Z)" disabled={!editor.canUndo} onClick={editor.undo}>
                ↶
              </button>
              <button className="btn ghost small" title="Wiederholen (Strg+Y)" disabled={!editor.canRedo} onClick={editor.redo}>
                ↷
              </button>
              <select value={snapMode} title="Einrasten" style={{ width: 120 }} onChange={(e) => setSnapMode(e.target.value as SnapMode)}>
                <option value="bar">Raster: Takt</option>
                <option value="beat">Raster: Beat</option>
                <option value="half">Raster: ½ Beat</option>
                <option value="off">Raster: aus</option>
              </select>
              <button className="btn ghost small" title="herauszoomen" onClick={() => setZoom(Math.max(1, zoom / 1.5))}>
                −
              </button>
              <button className="btn ghost small" title="hineinzoomen" onClick={() => setZoom(Math.min(64, zoom * 1.5))}>
                +
              </button>
              <button className="btn ghost small" title="ganze Show" onClick={() => setZoom(1)}>
                ⤢
              </button>
              <span className="unit" style={{ whiteSpace: "nowrap", minWidth: 70 }}>
                {editor.saving ? "speichert…" : editor.error ? "⚠ Fehler" : "gespeichert"}
              </span>
            </div>
            <EffectBar effects={effects} shaders={shaders} looks={looks} selected={pick} onPick={setPick} />
          </div>
        ) : (
          <div />
        )}
        {show && <CuePads analysis={analysis} duration={duration} apply={apply} onAdded={(id) => setSelection(new Set([id]))} />}
        {show ? (
          <TimelineEditor
            show={show}
            apply={apply}
            analysis={analysis}
            duration={duration}
            selection={selection}
            setSelection={(s) => {
              setSelection(s);
              if (s.size) {
                setSelectedLayer(null);
                setPanel("edit");
              }
            }}
            selectedLayer={selectedLayer}
            setSelectedLayer={(id) => {
              setSelectedLayer(id);
              setSelection(new Set());
              setPanel("edit");
            }}
            onSeek={async (t) => setPlayback(await api.seek(t))}
            errors={errors}
            snapMode={snapMode}
            zoom={zoom}
            setZoom={setZoom}
            defaultEffect={defaultEffect}
            onDropLook={async (lookId, at, li) => {
              const look = looks.find((l) => l.id === lookId);
              try {
                const items = await api.instantiateLook(slug, lookId, show.id, at);
                let ids: string[] = [];
                apply((s) => {
                  const r = insertLookClips(s, items, li, look?.name ?? "Look");
                  ids = r.ids;
                  return r.show;
                });
                setSelection(new Set(ids));
              } catch (e) {
                notify((e as Error).message, "error");
              }
            }}
          />
        ) : (
          <div className="timeline" style={{ display: "grid", placeItems: "center" }}>
            <span className="hint">Show links auswählen oder erstellen.</span>
          </div>
        )}
        </div>
      </Panes>

      <div className="pane" style={{ display: "flex", flexDirection: "column" }}>
        <div className="row" style={{ marginBottom: 12 }}>
          {(
            [
              ["edit", "Bearbeiten"],
              ["json", "JSON"],
              ["issues", "Prüfung"],
              ["history", "Verlauf"],
              ["shader", "Shader"],
            ] as const
          )
            .filter(([k]) => expert || (k !== "json" && k !== "shader"))
            .map(([k, label]) => (
            <button key={k} className={`btn small${panel === k ? " active" : ""}`} onClick={() => setPanel(k)}>
              {label}
            </button>
          ))}
        </div>
        <div style={{ flex: 1, minHeight: 0 }}>
          {!show && panel !== "shader" && <p className="hint">Keine Show geladen.</p>}
          {show && panel === "edit" && (
            <Inspector
              show={show}
              selection={selection}
              selectedLayer={selectedLayer}
              setSelectedLayer={setSelectedLayer}
              effects={effects}
              shaders={shaders}
              palettes={palettes}
              apply={apply}
              playhead={playhead}
              looks={looks}
              onLooksChanged={refreshLooks}
            />
          )}
          {show && panel === "json" && <JsonPanel show={show} onSave={async (s) => apply(() => s)} />}
          {show && panel === "issues" && <IssuesPanel slug={slug} show={show} />}
          {show && panel === "history" && <Versions showId={show.id} />}
          {panel === "shader" && <ShaderPanel slug={slug} />}
        </div>
      </div>
    </Panes>
  );
}
