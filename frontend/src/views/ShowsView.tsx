import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Timeline, usePlayhead } from "../components/Timeline";
import { Waveform } from "../components/Waveform";
import { useStore } from "../store";
import { Scene3D } from "../three/Scene3D";
import type { Analysis, Clip, EffectInfo, Issue, Show } from "../types";
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
        {formatTime(t)} / {formatTime(duration)}
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

function ClipPanel({ show, clipId, effects, onSave }: { show: Show; clipId: string | null; effects: EffectInfo[]; onSave: (s: Show) => Promise<void> }) {
  const clip = show.layers.flatMap((l) => l.clips).find((c) => c.id === clipId);
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setText(clip ? JSON.stringify(clip, null, 2) : "");
    setErr(null);
  }, [clip]);
  if (!clip) return <p className="hint">Clip in der Timeline anklicken, um ihn zu bearbeiten.</p>;
  const info = effects.find((e) => e.id === clip.effect);
  const apply = async (next: Clip | null) => {
    const s: Show = structuredClone(show);
    for (const l of s.layers) {
      const i = l.clips.findIndex((c) => c.id === clip.id);
      if (i >= 0) {
        if (next) l.clips[i] = next;
        else l.clips.splice(i, 1);
      }
    }
    await onSave(s);
  };
  return (
    <div>
      <div className="row between">
        <strong>{info?.name ?? clip.effect}</strong>
        <span className="badge">
          {clip.start.toFixed(2)}–{clip.end.toFixed(2)} s
        </span>
      </div>
      {info && <p className="hint">{info.description}</p>}
      <textarea rows={16} value={text} spellCheck={false} onChange={(e) => setText(e.target.value)} />
      {err && <div className="banner err">{err}</div>}
      <div className="row between" style={{ marginTop: 6 }}>
        <button
          className="btn primary small"
          onClick={async () => {
            try {
              await apply(JSON.parse(text));
              setErr(null);
            } catch (e) {
              setErr((e as Error).message);
            }
          }}
        >
          Übernehmen
        </button>
        <button className="btn danger small" onClick={() => apply(null)}>
          Clip löschen
        </button>
      </div>
      {info && (
        <>
          <h3>Parameter</h3>
          <table className="grid">
            <tbody>
              {Object.entries(info.params).map(([k, p]) => (
                <tr key={k}>
                  <td>
                    <code>{k}</code>
                  </td>
                  <td className="unit">
                    {p.type}
                    {p.options ? `: ${p.options.join(" | ")}` : ""} = {JSON.stringify(p.default)}
                    <div>{p.description}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
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

function IssuesPanel({ slug, show }: { slug: string; show: Show }) {
  const [issues, setIssues] = useState<Issue[] | null>(null);
  const rev = useStore((s) => s.showRevision);
  useEffect(() => {
    setIssues(null);
    api.validate(slug, show.id).then(setIssues);
  }, [slug, show, rev]);
  if (!issues) return <p className="hint">Prüfe…</p>;
  if (issues.length === 0) return <div className="banner info">Keine Probleme gefunden.</div>;
  return (
    <div className="list">
      {issues.map((i, k) => (
        <div key={k} className="card" style={{ marginBottom: 0 }}>
          <span className={`badge ${i.severity === "error" ? "err" : "warn"}`}>{i.severity === "error" ? "Fehler" : "Hinweis"}</span>{" "}
          <span className="unit">
            {i.layer} / {i.clip}
          </span>
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

export function ShowsView() {
  const slug = useStore((s) => s.slug);
  const shows = useStore((s) => s.shows);
  const songs = useStore((s) => s.songs);
  const pb = useStore((s) => s.playback);
  const setPlayback = useStore((s) => s.setPlayback);
  const refreshShows = useStore((s) => s.refreshShows);
  const notify = useStore((s) => s.notify);
  const rev = useStore((s) => s.showRevision);
  const [show, setShow] = useState<Show | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [clipId, setClipId] = useState<string | null>(null);
  const [panel, setPanel] = useState<"clip" | "json" | "issues" | "shader">("clip");
  const [viewerCam, setViewerCam] = useState(false);
  const [effects, setEffects] = useState<EffectInfo[]>([]);
  const currentId = pb?.project === slug ? pb?.show : null;

  useEffect(() => {
    api.effects().then((r) => setEffects(r.effects));
  }, []);

  useEffect(() => {
    if (!slug || !currentId) {
      setShow(null);
      return;
    }
    api.show(slug, currentId).then(setShow).catch(() => setShow(null));
  }, [slug, currentId, rev]);

  const song = songs.find((s) => s.id === show?.song_id);
  useEffect(() => {
    setAnalysis(null);
    if (song?.status === "done") api.analysis(song.id).then(setAnalysis);
  }, [song?.id, song?.status]);

  const open = useCallback(
    async (id: string) => {
      if (!slug) return;
      setPlayback(await api.load(slug, id));
      setClipId(null);
    },
    [slug, setPlayback],
  );

  const save = useCallback(
    async (s: Show) => {
      if (!slug) return;
      const saved = await api.saveShow(slug, s);
      setShow(saved);
      await refreshShows();
    },
    [slug, refreshShows],
  );

  // space bar toggles playback
  useEffect(() => {
    const onKey = async (e: KeyboardEvent) => {
      if (e.code !== "Space" || (e.target as HTMLElement).closest("input, textarea, select")) return;
      e.preventDefault();
      const st = useStore.getState().playback;
      if (st?.show) setPlayback(await (st.playing ? api.pause() : api.play()));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setPlayback]);

  const duration = pb?.duration || analysis?.duration || show?.duration || 0;
  const errors = useMemo(() => pb?.clip_errors ?? {}, [pb?.clip_errors]);
  if (!slug) return null;

  return (
    <div className="view" style={{ gridTemplateColumns: "250px 1fr 360px" }}>
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

      <div className="pane flush" style={{ display: "grid", gridTemplateRows: "1fr auto 190px", minWidth: 0 }}>
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
          <Timeline
            show={show}
            analysis={analysis}
            duration={duration}
            selected={clipId}
            errors={errors}
            onSelect={(id) => {
              setClipId(id);
              setPanel("clip");
            }}
            onSeek={async (t) => setPlayback(await api.seek(t))}
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
              ["clip", "Clip"],
              ["json", "JSON"],
              ["issues", "Prüfung"],
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
          {show && panel === "clip" && <ClipPanel show={show} clipId={clipId} effects={effects} onSave={save} />}
          {show && panel === "json" && <JsonPanel show={show} onSave={save} />}
          {show && panel === "issues" && <IssuesPanel slug={slug} show={show} />}
          {panel === "shader" && <ShaderPanel slug={slug} />}
        </div>
      </div>
    </div>
  );
}
