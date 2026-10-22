import { useStore } from "../store";

const TOOLS: [string, string][] = [
  ["get_overview", "Raum, Betrachter, Strips, Songs und Shows auf einen Blick"],
  ["get_song_analysis", "Tempo, Beats, Takte, Abschnitte und Lautstärkekurven"],
  ["get_led_positions", "Einzelne LED-Positionen eines Strips"],
  ["list_effects / get_show_format", "Effektbibliothek und Show-Format"],
  ["create_show, add_clips, update_clips, remove_clips, update_show", "Shows programmieren"],
  ["write_shader / get_shader_api", "Eigene Effekte in Python/numpy"],
  ["validate", "Fehler und Hinweise prüfen"],
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
        <h2>KI-Shows über MCP</h2>
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
        <h3>Werkzeuge</h3>
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
      </div>
    </div>
  );
}
