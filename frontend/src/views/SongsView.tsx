import { Panes } from "../components/Panes";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { activity, InstrumentLanes, MOMENT_COLORS, MOMENT_LABELS } from "../components/InstrumentLanes";
import { SECTION_COLORS, sectionName, Waveform } from "../components/Waveform";
import { useStore } from "../store";
import type { Analysis, AppSettings, Song } from "../types";
import { EmptyState, Expert, Field, formatTime, Icon, NumberInput, TextInput, useContextMenu } from "../ui";
import { Help } from "../components/Help";
import { friendly } from "../errors";

function StatusBadge({ song }: { song: Song }) {
  switch (song.status) {
    case "done":
      return <span className="badge ok">analysiert</span>;
    case "error":
      return <span className="badge err" title={song.error ?? ""}>Fehler</span>;
    case "running":
      return (
        <span className="badge info" title={song.stage ?? ""}>
          {song.stage ? `${song.stage}${song.progress ? ` ${Math.round(song.progress * 100)} %` : ""}` : "analysiere…"}
        </span>
      );
    default:
      return <span className="badge">wartet</span>;
  }
}

/** Tempo: octave fixes for a wrongly detected tempo and fine tuning of the exact BPM. */
function TempoEditor({ song, analysis, onChange }: { song: Song; analysis: Analysis; onChange: (a: Analysis) => void }) {
  const notify = useStore((s) => s.notify);
  const [busy, setBusy] = useState(false);
  const run = async (call: Promise<{ bpm: number }>) => {
    setBusy(true);
    try {
      await call;
      onChange(await api.analysis(song.id));
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  const bpm = Math.round(analysis.bpm * 100) / 100;
  const nudge = (d: number) => run(api.setBpm(song.id, Math.round((bpm + d) * 10) / 10));
  return (
    <div className="tempo" title="Die Beats werden als gleichmäßiges Raster neu gesetzt, passend zu den erkannten Beats">
      <button className="btn small" disabled={busy} title="halbes Tempo" onClick={() => run(api.scaleTempo(song.id, 0.5))}>
        ÷2
      </button>
      <button className="btn small" disabled={busy} onClick={() => nudge(-1)}>
        −1
      </button>
      <button className="btn small" disabled={busy} onClick={() => nudge(-0.1)}>
        −0,1
      </button>
      <NumberInput value={bpm} step={0.1} min={30} max={300} disabled={busy} onChange={(v) => run(api.setBpm(song.id, v))} />
      <button className="btn small" disabled={busy} onClick={() => nudge(0.1)}>
        +0,1
      </button>
      <button className="btn small" disabled={busy} onClick={() => nudge(1)}>
        +1
      </button>
      <button className="btn small" disabled={busy} title="doppeltes Tempo" onClick={() => run(api.scaleTempo(song.id, 2))}>
        ×2
      </button>
      <span className="unit">BPM</span>
    </div>
  );
}

const NOW: { track: string; label: string; color: string }[] = [
  { track: "kick", label: "Kick", color: "#f87171" },
  { track: "snare", label: "Snare", color: "#facc15" },
  { track: "hihat", label: "Hi-Hat", color: "#94a3b8" },
  { track: "crash", label: "Crash", color: MOMENT_COLORS.crash },
  { track: "bass", label: "Bass", color: "#a78bfa" },
  { track: "vocal", label: "Gesang", color: "#2dd4bf" },
  { track: "keys", label: "Keys / Synth", color: "#60a5fa" },
  { track: "lead", label: "Melodie", color: "#93c5fd" },
  { track: "piano", label: "Klavier", color: "#fda4af" },
  { track: "guitar", label: "Gitarre", color: "#fdba74" },
  { track: "stab", label: "Stab", color: "#f0abfc" },
  { track: "pad", label: "Pad", color: "#c4b5fd" },
  { track: "arp", label: "Arpeggio", color: "#67e8f9" },
  { track: "fill", label: "Fill", color: MOMENT_COLORS.fill },
  { track: "build", label: "Build-up", color: MOMENT_COLORS.build },
  { track: "drop", label: "Drop", color: MOMENT_COLORS.drop },
  { track: "motif", label: "Motiv", color: "#34d399" },
];
const ZOOMS: { value: number; label: string }[] = [
  { value: 0, label: "ganzer Song" },
  { value: 30, label: "30 s" },
  { value: 10, label: "10 s" },
];

function savedZoom(): number {
  try {
    return Number(localStorage.getItem("lsg.songs.zoom") ?? 0) || 0;
  } catch {
    return 0;
  }
}

/** Plays the song in the browser with a running playhead, so the detected instruments can be checked by ear.
 * Does not touch the LEDs; a running show is paused. */
function SongPlayer({ song, analysis }: { song: Song; analysis: Analysis | null }) {
  const audio = useRef<HTMLAudioElement>(null);
  const setPlayback = useStore((s) => s.setPlayback);
  const [playing, setPlaying] = useState(false);
  const [t, setT] = useState(0);
  const [rate, setRate] = useState(1);
  const [zoom, setZoom] = useState(savedZoom);
  const duration = song.duration || analysis?.duration || 0;

  useEffect(() => {
    setPlaying(false);
    setT(0);
  }, [song.id]);
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const tick = () => {
      if (audio.current) setT(audio.current.currentTime);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);
  useEffect(() => {
    if (audio.current) audio.current.playbackRate = rate;
  }, [rate, song.id]);

  const toggle = async () => {
    const a = audio.current;
    if (!a) return;
    if (!a.paused) return a.pause();
    if (useStore.getState().playback?.playing) setPlayback(await api.pause()); // never two songs at once
    a.playbackRate = rate;
    await a.play();
  };
  const seek = (s: number) => {
    const a = audio.current;
    if (!a) return;
    a.currentTime = Math.max(0, Math.min(duration, s));
    setT(a.currentTime);
  };
  const toggleRef = useRef(toggle);
  toggleRef.current = toggle;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "Space" || (e.target as HTMLElement).closest("input, textarea, select, button")) return;
      e.preventDefault();
      void toggleRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const tracks = analysis?.tracks ?? {};
  const hasTracks = Object.keys(tracks).length > 0;
  // zoomed: the window runs with the playhead, a quarter of it already played
  const from = zoom && duration > zoom ? Math.max(0, Math.min(duration - zoom, t - zoom * 0.25)) : 0;
  const range: [number, number] | undefined = zoom && duration > zoom ? [from, from + zoom] : undefined;
  const section = analysis?.sections.find((s) => t >= s.start && t < s.end);
  const chord = analysis?.harmony?.chords.find(([s, d]) => t >= s && t < s + d);

  return (
    <>
      <audio
        ref={audio}
        src={`/api/songs/${song.id}/audio`}
        preload="auto"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onSeeked={(e) => setT(e.currentTarget.currentTime)}
      />
      <div className="song-transport">
        <button className="btn icon" title="Abspielen / Pause (Leertaste)" onClick={() => void toggle()}>
          <Icon name={playing ? "pause" : "play"} />
        </button>
        <button className="btn icon" title="Zum Anfang" onClick={() => (audio.current?.pause(), seek(0))}>
          <Icon name="stop" />
        </button>
        <span className="time">
          {formatTime(t)} / {formatTime(duration)}
        </span>
        {section && (
          <span className="row unit" style={{ gap: 4 }}>
            <span className="swatch" style={{ background: SECTION_COLORS[section.name] ?? "#64748b" }} /> {sectionName(section.name)} {section.label}
          </span>
        )}
        {chord && (
          <span className="unit" title="Akkord und Stufe in der Tonart">
            Akkord <strong style={{ color: "var(--text)" }}>{chord[2]}</strong> {chord[3]}
          </span>
        )}
        <span className="grow" />
        <select
          value={rate}
          title="Abspieltempo – langsamer hilft, einzelne Schläge zu prüfen"
          style={{ width: 100, flex: "none" }}
          onChange={(e) => setRate(+e.target.value)}
        >
          {[1, 0.75, 0.5].map((r) => (
            <option key={r} value={r}>
              Tempo {String(r).replace(".", ",")}×
            </option>
          ))}
        </select>
        {hasTracks && (
          <div className="seg" role="group" aria-label="Ausschnitt der Instrumente">
            {ZOOMS.map((z) => (
              <button
                key={z.value}
                className={zoom === z.value ? "on" : ""}
                title={z.value ? `Instrumente: ${z.label} um die Abspielposition, läuft mit` : "Instrumente: ganzer Song"}
                onClick={() => {
                  setZoom(z.value);
                  try {
                    localStorage.setItem("lsg.songs.zoom", String(z.value));
                  } catch {
                    /* no storage */
                  }
                }}
              >
                {z.label}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="card" style={{ padding: 8 }}>
        <Waveform analysis={analysis} duration={duration} height={150} curves position={t} onSeek={seek} />
      </div>
      {analysis && hasTracks && (
        <>
          <h3>
            Instrumente <Help id="analysis" />
          </h3>
          <div className="now-chips" title="Was die Analyse an der Abspielposition erkannt hat">
            {NOW.filter((n) => (n.track !== "piano" && n.track !== "guitar") || (tracks[n.track]?.length ?? 0) > 0).map((n) => {
              const a = activity(tracks[n.track], t);
              const lit = a > 0.02;
              return (
                <span
                  key={n.track}
                  className="now-chip"
                  style={
                    lit
                      ? {
                          background: `color-mix(in srgb, ${n.color} ${Math.round(15 + 70 * a)}%, transparent)`,
                          borderColor: n.color,
                          color: a > 0.4 ? "#fff" : undefined,
                        }
                      : undefined
                  }
                >
                  <span className="swatch" style={{ background: n.color }} /> {n.label}
                </span>
              );
            })}
          </div>
          <div className="card" style={{ padding: 8 }}>
            <InstrumentLanes analysis={analysis} duration={duration} position={t} range={range} onSeek={seek} />
          </div>
        </>
      )}
    </>
  );
}

function SongDetail({ song }: { song: Song }) {
  const refreshSongs = useStore((s) => s.refreshSongs);
  const notify = useStore((s) => s.notify);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  useEffect(() => {
    setAnalysis(null);
    if (song.status === "done") api.analysis(song.id).then(setAnalysis).catch(() => setAnalysis(null));
  }, [song.id, song.status]);
  const sectionsUsed = analysis ? [...new Set(analysis.sections.map((s) => s.name))] : [];
  return (
    <div>
      <h2>{song.title}</h2>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 16px", maxWidth: 720 }}>
        <Field label="Titel">
          <TextInput value={song.title} onChange={async (title) => (await api.updateSong(song.id, { title }), refreshSongs())} />
        </Field>
        <Field label="Interpret">
          <TextInput value={song.artist} onChange={async (artist) => (await api.updateSong(song.id, { artist }), refreshSongs())} />
        </Field>
      </div>
      <div className="row" style={{ margin: "6px 0 14px" }}>
        <StatusBadge song={song} />
        <span className="badge">{formatTime(song.duration)}</span>
        {analysis && <span className="badge">{analysis.beats.length} Beats</span>}
        {analysis && <span className="badge">{analysis.downbeats.length} Takte</span>}
        {analysis && <span className="badge">{analysis.sections.length} Abschnitte</span>}
        {analysis && (
          <span className={`badge ${analysis.beat_source === "beat_this" ? "info" : ""}`} title={analysis.beat_note ?? ""}>
            Beats: {analysis.beat_source === "beat_this" ? "KI-Modell" : "Standard"}
          </span>
        )}
        {analysis && <span className="badge">{analysis.beats_per_bar ?? 4}/4-Takt</span>}
        {analysis?.harmony?.key && (
          <span className="badge" title={`Aus den erkannten Noten; Sicherheit ${Math.round(analysis.harmony.confidence * 100)} %`}>
            Tonart: {analysis.harmony.key}
          </span>
        )}
        {analysis?.harmony?.key && (
          <Help id="harmony" />
        )}
        {analysis?.stems && (
          <span
            className={`badge ${analysis.stems?.startsWith("demucs") ? "info" : ""}`}
            title={
              analysis.stems === "demucs6"
                ? "Mit dem KI-Modell Demucs in Schlagzeug, Bass, Gesang, Klavier, Gitarre und Rest getrennt"
                : analysis.stems === "demucs"
                  ? "Mit dem KI-Modell Hybrid Demucs in Schlagzeug, Bass, Gesang und Rest getrennt"
                  : "Ohne Trennmodell geschätzt (kein Gesang)"
            }
          >
            Instrumente: {analysis.stems === "demucs6" ? "getrennt (6 Spuren)" : analysis.stems === "demucs" ? "getrennt" : "geschätzt"}
          </span>
        )}
      </div>
      {song.status === "running" && (
        <div className="progress" title={song.stage ?? ""} style={{ margin: "0 0 12px", maxWidth: 720 }}>
          <div style={{ width: `${Math.round((song.progress ?? 0) * 100)}%` }} />
          <span>{song.stage ?? "Analyse läuft"}</span>
        </div>
      )}
      {analysis && (
        <Field label="Tempo" help={<Help id="tempo" />}>
          <TempoEditor song={song} analysis={analysis} onChange={setAnalysis} />
        </Field>
      )}
      {song.status === "error" && <div className="banner err">Analyse fehlgeschlagen: {friendly(song.error ?? "")}</div>}
      {analysis?.beat_note && <div className="banner info">Hinweis zur Beat-Erkennung: {analysis.beat_note}</div>}
      <SongPlayer song={song} analysis={analysis} />
      {analysis && (analysis.tracks && Object.keys(analysis.tracks).length ? (
        <>
          <div className="row" style={{ marginBottom: 12 }}>
            {Object.entries(MOMENT_LABELS).map(([k, label]) => (
              <span key={k} className="row unit">
                <span className="swatch" style={{ background: MOMENT_COLORS[k] }} /> {label}
              </span>
            ))}
            <span className="unit">· Noten: Höhe = Tonhöhe, Helligkeit = Lautstärke</span>
          </div>
        </>
      ) : (
        <div className="banner info">
          Diese Analyse kennt noch keine Instrumente. „Neu analysieren“ trennt Schlagzeug, Bass, Gesang und den Rest und findet
          Noten, Fills, Build-ups und Drops – darauf reagieren Shows dann viel genauer. Ein von Hand gesetztes Tempo bleibt erhalten.
        </div>
      ))}
      {analysis && (
        <>
          <div className="row" style={{ marginBottom: 12 }}>
            {sectionsUsed.map((n) => (
              <span key={n} className="row unit">
                <span className="swatch" style={{ background: SECTION_COLORS[n] ?? "#64748b" }} /> {sectionName(n)}
              </span>
            ))}
            <span className="row unit">
              <span className="swatch" style={{ background: "#f87171" }} /> Bass
            </span>
            <span className="row unit">
              <span className="swatch" style={{ background: "#ffd400" }} /> Mitten
            </span>
            <span className="row unit">
              <span className="swatch" style={{ background: "#38bdf8" }} /> Höhen
            </span>
          </div>
          <h3>
            Abschnitte <Help id="songform" />
          </h3>
          <table className="grid" style={{ maxWidth: 720 }}>
            <thead>
              <tr>
                <th>Start</th>
                <th>Ende</th>
                <th>Abschnitt</th>
                <th title="Gleiche Buchstaben klingen gleich; die Zahl zählt die Wiederholungen">Teil</th>
                <th>Takte</th>
                <th title="1 = ruhigster, 5 = intensivster Teil des Songs; ★ = Höhepunkt">Intensität</th>
              </tr>
            </thead>
            <tbody>
              {analysis.sections.map((s, i) => (
                <tr key={i}>
                  <td>{formatTime(s.start)}</td>
                  <td>{formatTime(s.end)}</td>
                  <td>
                    <span className="row">
                      <span className="swatch" style={{ background: SECTION_COLORS[s.name] ?? "#64748b" }} />
                      {sectionName(s.name)}
                    </span>
                  </td>
                  <td>
                    {s.label}
                    {(s.repeat ?? 1) > 1 ? <span className="unit"> ×{s.repeat}</span> : null}
                  </td>
                  <td>{s.bars || "–"}</td>
                  <td>
                    <span className="intensity" title={`Intensität ${s.intensity ?? 3} von 5`}>
                      {[1, 2, 3, 4, 5].map((k) => (
                        <span key={k} className={k <= (s.intensity ?? 3) ? "on" : ""} />
                      ))}
                      {s.peak && <strong title="Höhepunkt des Songs"> ★</strong>}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <div className="row" style={{ marginTop: 16 }}>
        <button
          className="btn small"
          disabled={song.status === "running"}
          title={analysis?.beats_edited ? "Das von Hand gesetzte Tempo bleibt erhalten" : undefined}
          onClick={async () => {
            await api.reanalyse(song.id);
            notify("Analyse gestartet – dauert etwa eine Minute");
            setTimeout(refreshSongs, 300);
          }}
        >
          Neu analysieren
        </button>
        <Expert>
        <button
          className="btn small ghost"
          disabled={song.status === "running"}
          title="Auch Beats und Tempo neu erkennen (ein von Hand gesetztes Tempo geht verloren)"
          onClick={async () => {
            await api.reanalyse(song.id, false);
            notify("Analyse gestartet – Tempo wird neu erkannt");
            setTimeout(refreshSongs, 300);
          }}
        >
          … mit neuer Tempo-Erkennung
        </button>
        </Expert>
      </div>
    </div>
  );
}

function TrackerSetting() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const songs = useStore((s) => s.songs);
  useEffect(() => {
    api.settings().then(setSettings);
  }, [songs]);
  if (!settings) return null;
  const bt = settings.beat_this;
  const sep = settings.separation;
  return (
    <div className="card">
      <Field label="Beat-Erkennung">
        <select value={settings.beat_tracker} onChange={async (e) => setSettings(await api.saveSettings({ beat_tracker: e.target.value as AppSettings["beat_tracker"] }))}>
          <option value="auto">automatisch (KI-Modell wenn verfügbar)</option>
          <option value="librosa">Standard (schnell)</option>
          <option value="beat_this" disabled={!bt.installed}>
            KI-Modell beat_this{bt.installed ? "" : " (nicht installiert)"}
          </option>
        </select>
      </Field>
      <Field label="Instrumente">
        <select value={settings.stems ?? "auto"} onChange={async (e) => setSettings(await api.saveSettings({ stems: e.target.value as AppSettings["stems"] }))}>
          <option value="auto">automatisch (beste verfügbare Trennung)</option>
          <option value="demucs6" disabled={!sep?.six}>
            6 Spuren: mit Klavier und Gitarre{sep?.six ? "" : " (nicht installiert)"}
          </option>
          <option value="demucs" disabled={!sep?.four}>
            4 Spuren: Schlagzeug, Bass, Gesang, Rest{sep?.four ? "" : " (nicht installiert)"}
          </option>
          <option value="approx">geschätzt (schnell, ohne Gesang)</option>
        </select>
      </Field>
      <p className="hint" style={{ margin: 0 }}>
        {bt.installed
          ? bt.error
            ? `KI-Modell installiert, aber nicht ladbar: ${bt.error}`
            : "KI-Modell installiert (genauere Beats und Takte, langsamer). Gilt für neue Analysen."
          : 'Für genauere Beats: pip install -e ".[ml]" (installiert PyTorch, ca. 1 GB).'}
      </p>
    </div>
  );
}

export function SongsView() {
  const songs = useStore((s) => s.songs);
  const refreshSongs = useStore((s) => s.refreshSongs);
  const notify = useStore((s) => s.notify);
  const [selected, setSelected] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const song = songs.find((s) => s.id === selected) ?? songs[0];
  const ctx = useContextMenu();

  const remove = async (s: Song) => {
    if (!confirm(`„${s.title}“ löschen? Audio und Analyse werden entfernt.`)) return;
    try {
      await api.deleteSong(s.id);
      notify(`„${s.title}“ gelöscht`, "success");
    } catch (e) {
      notify((e as Error).message, "error");
    }
    await refreshSongs();
  };

  // poll while an analysis is running (events also trigger refreshes)
  useEffect(() => {
    if (!songs.some((s) => s.status === "pending" || s.status === "running")) return;
    const id = setInterval(refreshSongs, 2000);
    return () => clearInterval(id);
  }, [songs, refreshSongs]);

  const upload = async (files: FileList | File[]) => {
    for (const f of Array.from(files)) {
      setBusy((b) => b + 1);
      try {
        const s = await api.uploadSong(f);
        setSelected(s.id);
        notify(`„${s.title}" hochgeladen – Analyse läuft`, "success");
      } catch (e) {
        notify(`${f.name}: ${(e as Error).message}`, "error");
      }
      setBusy((b) => b - 1);
      await refreshSongs();
    }
  };

  return (
    <Panes id="songs" sizes={[420, null]} className="view">
      <div className="pane">
        <h2>Songs</h2>
        <div
          className={`dropzone${over ? " over" : ""}`}
          onClick={() => input.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setOver(false);
            void upload(e.dataTransfer.files);
          }}
        >
          <Icon name="music" />
          <div style={{ marginTop: 6 }}>{busy ? "Lade hoch…" : "Audiodateien hierher ziehen oder klicken"}</div>
          <div className="hint" style={{ margin: 0 }}>
            mp3, wav, flac, ogg, aiff
          </div>
          <input
            ref={input}
            type="file"
            accept=".mp3,.wav,.flac,.ogg,.oga,.aiff,.aif,audio/*"
            multiple
            hidden
            onChange={(e) => e.target.files && upload(e.target.files)}
          />
        </div>
        <div className="row" style={{ margin: "10px 0 14px" }}>
          <button
            className="btn small"
            onClick={async () => {
              const s = await api.demoSong(124);
              setSelected(s.id);
              await refreshSongs();
              notify("Demo-Song erzeugt", "success");
            }}
          >
            Demo-Song erzeugen
          </button>
        </div>
        <Expert>
          <TrackerSetting />
        </Expert>
        <div className="list">
          {songs.length === 0 && (
            <EmptyState title="Noch keine Songs">
              Zieh eine Audiodatei in das Feld oben oder erzeuge einen Demo-Song. Die Analyse erkennt dann Takt, Abschnitte, Instrumente
              und Akkorde.
            </EmptyState>
          )}
          {songs.map((s) => (
            <div
              key={s.id}
              className={`list-item${song?.id === s.id ? " active" : ""}`}
              onClick={() => setSelected(s.id)}
              onContextMenu={(e) =>
                ctx.open(e, [
                  {
                    label: "Neu analysieren",
                    onClick: async () => {
                      await api.reanalyse(s.id);
                      setTimeout(refreshSongs, 300);
                    },
                  },
                  {
                    label: "Neu analysieren (Tempo neu erkennen)",
                    onClick: async () => {
                      await api.reanalyse(s.id, false);
                      setTimeout(refreshSongs, 300);
                    },
                  },
                  { label: "Löschen", danger: true, onClick: () => void remove(s) },
                ])
              }
            >
              <Icon name="music" />
              <div className="grow">
                <div>{s.title}</div>
                <div className="meta">
                  {s.artist || "—"} · {formatTime(s.duration)}
                </div>
              </div>
              <StatusBadge song={s} />
            </div>
          ))}
        </div>
        {songs.length > 0 && <p className="hint">Rechtsklick auf einen Song: neu analysieren oder löschen.</p>}
        {ctx.menu}
      </div>
      <div className="pane">{song ? <SongDetail song={song} /> : <p className="hint">Lade einen Song hoch, um ihn zu analysieren.</p>}</div>
    </Panes>
  );
}
