import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { SECTION_COLORS, Waveform } from "../components/Waveform";
import { useStore } from "../store";
import type { Analysis, Song } from "../types";
import { Field, formatTime, Icon, TextInput } from "../ui";

function StatusBadge({ song }: { song: Song }) {
  switch (song.status) {
    case "done":
      return <span className="badge ok">analysiert</span>;
    case "error":
      return <span className="badge err" title={song.error ?? ""}>Fehler</span>;
    case "running":
      return <span className="badge info">analysiere…</span>;
    default:
      return <span className="badge">wartet</span>;
  }
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
        {analysis && <span className="badge info">{analysis.bpm.toFixed(1)} BPM</span>}
        {analysis && <span className="badge">{analysis.beats.length} Beats</span>}
        {analysis && <span className="badge">{analysis.downbeats.length} Takte</span>}
        {analysis && <span className="badge">{analysis.sections.length} Abschnitte</span>}
      </div>
      {song.status === "error" && <div className="banner err">Analyse fehlgeschlagen: {song.error}</div>}
      <div className="card" style={{ padding: 8 }}>
        <Waveform analysis={analysis} duration={song.duration} height={150} curves />
      </div>
      {analysis && (
        <>
          <div className="row" style={{ marginBottom: 12 }}>
            {sectionsUsed.map((n) => (
              <span key={n} className="row unit">
                <span className="swatch" style={{ background: SECTION_COLORS[n] ?? "#64748b" }} /> {n}
              </span>
            ))}
            <span className="row unit">
              <span className="swatch" style={{ background: "#ff2d95" }} /> Bass
            </span>
            <span className="row unit">
              <span className="swatch" style={{ background: "#ffd400" }} /> Mitten
            </span>
            <span className="row unit">
              <span className="swatch" style={{ background: "#00d4ff" }} /> Höhen
            </span>
          </div>
          <h3>Abschnitte</h3>
          <table className="grid" style={{ maxWidth: 720 }}>
            <thead>
              <tr>
                <th>Start</th>
                <th>Ende</th>
                <th>Abschnitt</th>
                <th>Ähnlichkeit</th>
                <th>Energie</th>
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
                      {s.name}
                    </span>
                  </td>
                  <td>{s.label}</td>
                  <td>
                    <div style={{ background: "var(--bg-4)", borderRadius: 3, height: 6, width: 120 }}>
                      <div style={{ width: `${Math.min(100, s.energy * 160)}%`, height: "100%", background: "var(--accent)", borderRadius: 3 }} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <div className="row" style={{ marginTop: 16 }}>
        {analysis && (
          <>
            <span className="unit">Tempo falsch erkannt?</span>
            {[
              [0.5, "÷2"],
              [2, "×2"],
            ].map(([f, label]) => (
              <button
                key={label}
                className="btn small"
                title={f === 2 ? "doppeltes Tempo (Beats halbieren den Abstand)" : "halbes Tempo"}
                onClick={async () => {
                  const r = await api.scaleTempo(song.id, f as number);
                  setAnalysis(await api.analysis(song.id));
                  notify(`Tempo jetzt ${r.bpm.toFixed(1)} BPM`, "success");
                }}
              >
                Tempo {label}
              </button>
            ))}
            <span style={{ width: 12 }} />
          </>
        )}
        <button
          className="btn small"
          onClick={async () => {
            await api.reanalyse(song.id);
            notify("Analyse gestartet");
            setTimeout(refreshSongs, 300);
          }}
        >
          Neu analysieren
        </button>
        <button
          className="btn danger small"
          onClick={async () => {
            if (!confirm(`„${song.title}" löschen?`)) return;
            await api.deleteSong(song.id);
            await refreshSongs();
          }}
        >
          <Icon name="trash" /> Löschen
        </button>
      </div>
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
    <div className="view split">
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
        <div className="list">
          {songs.length === 0 && <p className="hint">Noch keine Songs.</p>}
          {songs.map((s) => (
            <div key={s.id} className={`list-item${song?.id === s.id ? " active" : ""}`} onClick={() => setSelected(s.id)}>
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
      </div>
      <div className="pane">{song ? <SongDetail song={song} /> : <p className="hint">Lade einen Song hoch, um ihn zu analysieren.</p>}</div>
    </div>
  );
}
