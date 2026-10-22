import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { formatTime } from "../ui";

const EXAMPLES = [
  "Ruhiger Start in Blautönen, im Refrain auf jeden Beat pulsieren, bei Drops Wellen von links nach rechts durch mein Blickfeld.",
  "Atmosphärisch und dunkel: langsame Farbwolken, nur Akzente auf den Taktanfängen, Höhepunkt im letzten Refrain.",
  "Party: kräftige Farben, Lauflichter im Takt, kurze Stroboskop-Momente vor jedem Refrain.",
];

/** Minimal inline markdown: **bold** and `code`. */
function Md({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("**") && p.endsWith("**") ? (
          <strong key={i}>{p.slice(2, -2)}</strong>
        ) : p.startsWith("`") && p.endsWith("`") ? (
          <code key={i}>{p.slice(1, -1)}</code>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

function Generator() {
  const slug = useStore((s) => s.slug);
  const songs = useStore((s) => s.songs);
  const shows = useStore((s) => s.shows);
  const run = useStore((s) => s.aiRun);
  const setRun = useStore((s) => s.setAiRun);
  const setPlayback = useStore((s) => s.setPlayback);
  const setTab = useStore((s) => s.setTab);
  const notify = useStore((s) => s.notify);
  const [claude, setClaude] = useState<{ installed: boolean; version: string | null } | null>(null);
  const [song, setSong] = useState("");
  const [name, setName] = useState("KI-Show");
  const [target, setTarget] = useState("new");
  const [prompt, setPrompt] = useState(EXAMPLES[0]);
  const log = useRef<HTMLDivElement>(null);
  const analysed = songs.filter((s) => s.status === "done");
  const songId = song || analysed[0]?.id || "";
  const busy = run?.status === "running";

  useEffect(() => {
    api.aiStatus().then((s) => {
      setClaude(s.claude);
      if (s.run) setRun(s.run);
    });
  }, [setRun]);
  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight });
  }, [run?.events.length]);

  if (!claude) return <p className="hint">Prüfe Claude Code…</p>;
  if (!claude.installed)
    return (
      <div className="banner err">
        Claude Code wurde nicht gefunden. Installieren (siehe claude.com/claude-code) und einmal <span className="kbd">claude</span> im Terminal starten und anmelden – danach
        funktioniert die Generierung hier mit deinem Claude-Abo.
      </div>
    );
  return (
    <>
      <p className="hint">
        Nutzt dein lokales Claude Code ({claude.version}) mit deinem Claude-Abo – es entstehen keine API-Kosten, die Nutzung zählt zu den Limits deines Abos.
        Claude bekommt nur die Werkzeuge dieser App (kein Datei- oder Shell-Zugriff).
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 16px" }}>
        <div>
          <label className="unit">Song</label>
          <select value={songId} onChange={(e) => setSong(e.target.value)}>
            {analysed.length === 0 && <option value="">(erst einen Song analysieren)</option>}
            {analysed.map((s) => (
              <option key={s.id} value={s.id}>
                {s.artist ? `${s.artist} – ` : ""}
                {s.title}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="unit">Ziel</label>
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="new">neue Show anlegen</option>
            {shows.map((s) => (
              <option key={s.id} value={s.id}>
                überarbeiten: {s.name}
              </option>
            ))}
          </select>
        </div>
      </div>
      {target === "new" && (
        <div style={{ marginTop: 8 }}>
          <label className="unit">Name der Show</label>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
      )}
      <div style={{ marginTop: 8 }}>
        <label className="unit">Was soll die Show machen?</label>
        <textarea rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)} style={{ fontFamily: "inherit", fontSize: 14 }} />
        <div className="row" style={{ marginTop: 4, gap: 4 }}>
          {EXAMPLES.map((ex, i) => (
            <button key={i} className="btn ghost small" onClick={() => setPrompt(ex)}>
              Beispiel {i + 1}
            </button>
          ))}
        </div>
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        <button
          className="btn primary"
          disabled={busy || !slug || !songId || prompt.trim().length < 3}
          onClick={async () => {
            try {
              setRun(await api.aiRun({ project: slug!, prompt, song_id: songId || null, show_name: name.trim() || "KI-Show", show_id: target === "new" ? null : target }));
            } catch (e) {
              notify((e as Error).message, "error");
            }
          }}
        >
          {busy ? "KI arbeitet…" : "Show generieren"}
        </button>
        {busy && (
          <button className="btn danger" onClick={async () => setRun(await api.aiCancel())}>
            Abbrechen
          </button>
        )}
      </div>
      {run && (
        <div className="card" style={{ marginTop: 12 }}>
          <div className="row between" style={{ marginBottom: 6 }}>
            <strong>
              {run.status === "running" ? "Läuft" : run.status === "done" ? "Fertig" : run.status === "cancelled" ? "Abgebrochen" : "Fehler"}
            </strong>
            <span className="unit">
              {run.model ?? ""} {run.turns ? `· ${run.turns} Schritte` : ""} {run.duration_s ? `· ${formatTime(run.duration_s)}` : ""}
            </span>
          </div>
          <div ref={log} style={{ maxHeight: 260, overflow: "auto", fontSize: 13 }}>
            {run.events.map((e, i) => (
              <div key={i} className="row" style={{ alignItems: "flex-start", gap: 8, padding: "3px 0", flexWrap: "nowrap" }}>
                <span className="unit" style={{ width: 44, flex: "none", textAlign: "right" }}>
                  {formatTime(e.time).replace(/\.\d$/, "")}
                </span>
                <span className={`badge ${e.kind === "tool" ? "info" : e.kind === "error" ? "err" : e.kind === "warn" ? "warn" : ""}`} style={{ flex: "none" }}>
                  {e.kind === "tool" ? "Werkzeug" : e.kind === "text" ? "Claude" : e.kind === "info" ? "Info" : "Hinweis"}
                </span>
                <span style={{ whiteSpace: "pre-wrap" }}>
                  <Md text={e.text} />
                  {e.detail && <span className="unit"> · {e.detail}</span>}
                </span>
              </div>
            ))}
          </div>
          {run.result && (
            <div className="banner info" style={{ marginTop: 8, whiteSpace: "pre-wrap", color: "var(--text)" }}>
              <Md text={run.result} />
            </div>
          )}
          {run.error && run.status !== "cancelled" && <div className="banner err" style={{ marginTop: 8 }}>{run.error}</div>}
          {run.status === "done" && run.show_ids.length > 0 && slug && (
            <button
              className="btn primary small"
              onClick={async () => {
                setPlayback(await api.load(slug, run.show_ids[run.show_ids.length - 1]));
                setTab("shows");
              }}
            >
              Show öffnen
            </button>
          )}
        </div>
      )}
    </>
  );
}

const TOOLS: [string, string][] = [
  ["get_overview", "Raum, Betrachter, Strips, Songs und Shows auf einen Blick"],
  ["get_song_analysis", "Tempo, Beats, Takte, Abschnitte und Lautstärkekurven"],
  ["get_led_positions", "Einzelne LED-Positionen eines Strips"],
  ["list_effects / get_show_format", "Effektbibliothek und Show-Format"],
  ["create_show, add_clips, update_clips, remove_clips, update_show", "Shows programmieren"],
  ["write_shader / get_shader_api", "Eigene Effekte in Python/numpy"],
  ["validate / analyze_power", "Fehler, Hinweise und Strombedarf prüfen"],
  ["list_looks / apply_look", "Wiederverwendbare Clip-Gruppen (in Beats) einsetzen"],
  ["list_show_versions / restore_show_version", "Versionen ansehen und zurückrollen"],
  ["render_snapshot / render_timeline", "Bilder zur Selbstkontrolle der KI"],
  ["preview / playback", "Show in der App abspielen"],
];

export function AiView() {
  const slug = useStore((s) => s.slug);
  const origin = location.port === "5173" ? `${location.protocol}//${location.hostname}:8000` : location.origin;
  const url = `${origin}/mcp`;
  const desktop = JSON.stringify({ mcpServers: { lightshow: { command: "npx", args: ["-y", "mcp-remote", url] } } }, null, 2);
  return (
    <div className="view">
      <div className="pane" style={{ maxWidth: 900 }}>
        <h2>KI-Shows</h2>
        <div className="card">
          <strong>Show mit KI erstellen</strong>
          <Generator />
        </div>
        <details className="fold">
          <summary>
            <span>Eigener KI-Client über MCP</span>
            <span className="unit">für Claude Desktop, Claude Code und andere KI-Programme</span>
          </summary>
          <p className="hint" style={{ fontSize: 14 }}>
            Die App stellt einen MCP-Server bereit. Eine KI wie Claude kennt darüber den Raum, die LED-Positionen, die Betrachterposition und die
            Musikanalyse und kann Shows direkt hier hinein programmieren. Änderungen erscheinen sofort in der Vorschau.
          </p>
          <div className="card">
            <strong>MCP-Endpunkt</strong>
            <pre className="code">{url}</pre>
            <p className="hint">Streamable HTTP, nur lokal erreichbar. Die App muss laufen, solange die KI arbeitet.</p>
          </div>
          <div className="card">
            <strong>Claude Code</strong>
            <pre className="code">claude mcp add --transport http lightshow {url}</pre>
          </div>
          <div className="card">
            <strong>Claude Desktop</strong>
            <p className="hint">In claude_desktop_config.json eintragen (benötigt Node.js für mcp-remote):</p>
            <pre className="code">{desktop}</pre>
          </div>
          <div className="card">
            <strong>Beispiel-Auftrag</strong>
            <pre className="code" style={{ whiteSpace: "pre-wrap" }}>
              {`Schau dir mit get_overview mein Projekt${slug ? ` „${slug}"` : ""} an und analysiere den Song.
Erstelle eine Show, die im Intro ruhig mit Blautönen beginnt, im Refrain auf jeden Beat
pulsiert und bei Drops Wellen von links nach rechts durch mein Blickfeld schickt.
Prüfe das Ergebnis mit render_timeline und starte danach preview.`}
            </pre>
          </div>
          <h3 style={{ marginTop: 14 }}>Werkzeuge</h3>
          <table className="grid">
            <tbody>
              {TOOLS.map(([k, v]) => (
                <tr key={k}>
                  <td>
                    <code>{k}</code>
                  </td>
                  <td className="unit">{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </div>
    </div>
  );
}
