import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { SERIES } from "../calibration";
import { LineChart } from "../components/LineChart";
import { Versions } from "../components/Versions";
import { Waveform } from "../components/Waveform";
import { useStore } from "../store";
import { Scene3D } from "../three/Scene3D";
import { Inspector } from "../editor/Inspector";
import { allClips, deleteClips, moveClips, pasteClips, type SnapMode } from "../editor/ops";
import { EffectBar, TimelineEditor, usePlayhead } from "../editor/TimelineEditor";
import { useShowEditor } from "../editor/useShowEditor";
import type { Analysis, Clip, EffectInfo, Issue, PowerReport, Show } from "../types";
import { Field, formatTime, Icon } from "../ui";

function NewShowForm({ onCreated }: { onCreated: (id: string) => void }) {
  const slug = useStore((s) => s.slug)!;
  const songs = useStore((s) => s.songs);
  const refreshShows = useStore((s) => s.refreshShows);
  const notify = useStore((s) => s.notify);
  const [name, setName] = useState("");
  const [song, setSong] = useState("");
  const [template, setTemplate] = useState("starter");
  const songId = song || songs[0]?.id || "";
  return (
    <div className="card">
      <strong>Neue Show</strong>
      <div style={{ marginTop: 8 }}>
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
        <button
          className="btn primary"
          style={{ width: "100%" }}
          onClick={async () => {
            try {
              const show = await api.createShow(slug, name.trim() || "Neue Show", songId || null, template);
              await refreshShows();
              onCreated(show.id);
              setName("");
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
  const live = pb.mode === "live";
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
      <button
        className={`btn small${live ? " live" : ""}`}
        title="Live: Frames an die WLED-Controller senden"
        onClick={async () => setPlayback(await api.mode(live ? "preview" : "live"))}
      >
        {live ? "● LIVE" : "Vorschau"}
      </button>
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
  const [devices, setDevices] = useState<{ index: number; name: string; default: boolean }[] | null>(null);
  const [device, setDevice] = useState<number | null>(null);
  const live = pb?.live_input;
  useEffect(() => {
    api.liveDevices().then(setDevices).catch(() => setDevices([]));
  }, []);
  return (
    <div className={`card${live ? " selected" : ""}`}>
      <strong>Live-Eingang (Mikrofon)</strong>
      <p className="hint">Ohne vorbereiteten Song: die Show „Live (Mikrofon)“ reagiert in Echtzeit auf Tempo, Bass und Höhen – z. B. für Musik von Spotify oder eine Party.</p>
      {live ? (
        <>
          <div className="row" style={{ marginBottom: 6 }}>
            <span className="badge info">{live.bpm.toFixed(0)} BPM</span>
            <span className="unit" title={live.device} style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 140 }}>
              {live.device}
            </span>
          </div>
          {(["low", "mid", "high"] as const).map((k) => (
            <div key={k} className="row" style={{ flexWrap: "nowrap", marginBottom: 3 }}>
              <span className="unit" style={{ width: 48 }}>{k === "low" ? "Bass" : k === "mid" ? "Mitten" : "Höhen"}</span>
              <div style={{ flex: 1, height: 6, background: "var(--bg-4)", borderRadius: 3 }}>
                <div style={{ width: `${Math.round((live.levels[k] ?? 0) * 100)}%`, height: "100%", background: "var(--accent-2)", borderRadius: 3 }} />
              </div>
            </div>
          ))}
          <button className="btn small active" style={{ marginTop: 6 }} onClick={async () => setPlayback(await api.liveInput(false))}>
            Live-Eingang beenden
          </button>
        </>
      ) : devices && devices.length === 0 ? (
        <span className="unit">Kein Eingangsgerät gefunden.</span>
      ) : (
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <select value={device ?? ""} onChange={(e) => setDevice(e.target.value === "" ? null : +e.target.value)}>
            <option value="">Standard-Eingang</option>
            {devices?.map((d) => (
              <option key={d.index} value={d.index}>
                {d.name}
              </option>
            ))}
          </select>
          <button
            className="btn small"
            onClick={async () => {
              try {
                setPlayback(await api.liveInput(true, null, device));
              } catch (e) {
                notify((e as Error).message, "error");
              }
            }}
          >
            Starten
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
      <strong>Export (xLights / FPP)</strong>
      <p className="hint">FSEQ-Sequenz mit kalibrierten Werten, Audio und Kanal-Zuordnung als ZIP – z. B. zum Abspielen ohne PC auf einem Falcon Player.</p>
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
  const [viewerCam, setViewerCam] = useState(false);
  const [effects, setEffects] = useState<EffectInfo[]>([]);
  const [palettes, setPalettes] = useState<Record<string, string[]>>({});
  const [shaders, setShaders] = useState<string[]>([]);
  const [snapMode, setSnapMode] = useState<SnapMode>("beat");
  const [zoom, setZoom] = useState(1);
  const [pick, setPick] = useState("pulse");
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
  const defaultEffect = effects.find((e) => e.id === pick) ?? { id: pick };

  return (
    <div className="view" style={{ gridTemplateColumns: "230px minmax(0, 1fr) 380px" }}>
      <div className="pane">
        <h2>Shows</h2>
        <div className="list" style={{ marginBottom: 12 }}>
          {shows.length === 0 && <p className="hint">Noch keine Shows in diesem Projekt.</p>}
          {shows.map((s) => {
            const sg = songs.find((x) => x.id === s.song_id);
            return (
              <div key={s.id} className={`list-item${currentId === s.id ? " active" : ""}`} onClick={() => open(s.id)}>
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
        <NewShowForm onCreated={open} />
        <LiveInputCard />
        {show && <ExportCard slug={slug} showId={show.id} />}
        {show && (
          <button
            className="btn danger small"
            onClick={async () => {
              if (!confirm(`Show „${show.name}" löschen?`)) return;
              await api.deleteShow(slug, show.id);
              await api.load(slug, null).then(setPlayback);
              await refreshShows();
              notify("Show gelöscht");
            }}
          >
            <Icon name="trash" /> Show löschen
          </button>
        )}
      </div>

      <div className="pane flush" style={{ display: "grid", gridTemplateRows: "minmax(160px, 1fr) auto auto minmax(170px, 36vh)", minWidth: 0 }}>
        <div style={{ position: "relative" }}>
          <div className="canvas-wrap">
            <Scene3D viewerCam={viewerCam} />
          </div>
          <div className="overlay">
            <span className="badge">{show ? show.name : "Keine Show geladen"}</span>
            {pb && pb.render_ms > 0 && <span className="badge">{pb.render_ms.toFixed(1)} ms/Frame</span>}
            {Object.keys(errors).length > 0 && <span className="badge err">{Object.keys(errors).length} Clip-Fehler</span>}
          </div>
          <div className="overlay right">
            <button className={`btn small${viewerCam ? " active" : ""}`} onClick={() => setViewerCam((v) => !v)}>
              {viewerCam ? "Freie Kamera" : "Betrachter-Sicht"}
            </button>
          </div>
        </div>
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
            <EffectBar effects={effects} shaders={shaders} selected={pick} onPick={setPick} />
          </div>
        ) : (
          <div />
        )}
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
          />
        ) : (
          <div className="timeline" style={{ display: "grid", placeItems: "center" }}>
            <span className="hint">Show links auswählen oder erstellen.</span>
          </div>
        )}
      </div>

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
          ).map(([k, label]) => (
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
            />
          )}
          {show && panel === "json" && <JsonPanel show={show} onSave={async (s) => apply(() => s)} />}
          {show && panel === "issues" && <IssuesPanel slug={slug} show={show} />}
          {show && panel === "history" && <Versions showId={show.id} />}
          {panel === "shader" && <ShaderPanel slug={slug} />}
        </div>
      </div>
    </div>
  );
}
