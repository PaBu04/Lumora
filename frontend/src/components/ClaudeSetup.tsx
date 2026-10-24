import { useState } from "react";

const WINDOWS = typeof navigator !== "undefined" && /Windows/i.test(navigator.userAgent);

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="setup-step">
      <span className="setup-n">{n}</span>
      <div className="grow">
        <strong>{title}</strong>
        {children}
      </div>
    </div>
  );
}

/**
 * Step-by-step guide to connect the app with Claude Code. Shown when Claude Code is missing or a
 * run failed; `open` starts it unfolded. `onRecheck` asks the backend again for Claude Code.
 */
export function ClaudeSetup({ open: initial = false, onRecheck }: { open?: boolean; onRecheck?: () => Promise<void> }) {
  const [open, setOpen] = useState(initial);
  const [checking, setChecking] = useState(false);
  const install = WINDOWS
    ? [
        ["Windows (PowerShell)", "irm https://claude.ai/install.ps1 | iex"],
        ["macOS / Linux", "curl -fsSL https://claude.ai/install.sh | bash"],
      ]
    : [
        ["macOS / Linux", "curl -fsSL https://claude.ai/install.sh | bash"],
        ["Windows (PowerShell)", "irm https://claude.ai/install.ps1 | iex"],
      ];
  if (!open)
    return (
      <button className="btn ghost small" onClick={() => setOpen(true)}>
        Anleitung: App mit Claude verbinden
      </button>
    );
  return (
    <div className="card setup">
      <div className="row between" style={{ marginBottom: 6 }}>
        <strong>So verbindest du die App mit Claude</strong>
        {!initial && (
          <button className="btn ghost small" onClick={() => setOpen(false)}>
            Schließen
          </button>
        )}
      </div>
      <p className="hint" style={{ marginTop: 0 }}>
        Lumora erzeugt Shows mit Claude Code, dem Kommandozeilen-Programm von Anthropic. Es läuft auf deinem Rechner und nutzt dein Claude-Abo – es entstehen keine
        API-Kosten und du brauchst keinen API-Schlüssel. Die Einrichtung ist einmalig.
      </p>
      <Step n={1} title="Claude-Abo">
        <p className="hint">Du brauchst ein Claude-Konto mit Pro- oder Max-Abo (claude.ai). Mit dem kostenlosen Konto funktioniert Claude Code nicht.</p>
      </Step>
      <Step n={2} title="Claude Code installieren">
        <p className="hint">Ein Terminal öffnen (Windows: PowerShell) und diesen Befehl einfügen:</p>
        {install.map(([os, cmd]) => (
          <div key={os}>
            <span className="unit">{os}</span>
            <pre className="code">{cmd}</pre>
          </div>
        ))}
        <p className="hint">Alternativ mit Node.js 18 oder neuer:</p>
        <pre className="code">npm install -g @anthropic-ai/claude-code</pre>
      </Step>
      <Step n={3} title="Einmal anmelden">
        <p className="hint">Im Terminal Claude Code starten:</p>
        <pre className="code">claude</pre>
        <p className="hint">
          Beim ersten Start öffnet sich der Browser. Die Anmeldung mit dem Claude-Konto (Abo) wählen, nicht die Anthropic Console (API-Abrechnung). Danach im
          Terminal /exit eingeben.
        </p>
      </Step>
      <Step n={4} title="Prüfen">
        <p className="hint">In einem neuen Terminal muss dieser Befehl eine Versionsnummer zeigen:</p>
        <pre className="code">claude --version</pre>
        <p className="hint">Dann hier erneut prüfen. Findet die App Claude Code immer noch nicht, Lumora einmal beenden und neu starten.</p>
        {onRecheck && (
          <button
            className="btn small"
            disabled={checking}
            onClick={async () => {
              setChecking(true);
              try {
                await onRecheck();
              } finally {
                setChecking(false);
              }
            }}
          >
            {checking ? "Prüfe…" : "Erneut prüfen"}
          </button>
        )}
      </Step>
      <h3 style={{ margin: "14px 0 6px" }}>Wenn es nicht klappt</h3>
      <table className="grid setup-faq">
        <tbody>
          <tr>
            <td>„Claude Code wurde nicht gefunden“</td>
            <td className="unit">Terminal und Lumora neu starten, damit der neue Programmpfad bekannt ist. Prüfen, ob claude --version im Terminal funktioniert.</td>
          </tr>
          <tr>
            <td>Fehler zur Anmeldung („login“, „auth“)</td>
            <td className="unit">Im Terminal claude starten und mit /login neu anmelden. Danach die Generierung erneut starten.</td>
          </tr>
          <tr>
            <td>Modell nicht verfügbar</td>
            <td className="unit">Oben „Claude Code aktualisieren“ drücken (oder claude update im Terminal) oder ein anderes Modell wählen.</td>
          </tr>
          <tr>
            <td>„Claude erreicht die App nicht“</td>
            <td className="unit">
              Claude spricht über eine lokale Schnittstelle mit Lumora. Die App muss laufen, solange Claude arbeitet; eine Firewall darf Verbindungen zu
              localhost nicht blockieren.
            </td>
          </tr>
          <tr>
            <td>Nutzungslimit erreicht</td>
            <td className="unit">Das Abo hat ein Kontingent pro Zeitfenster. Später erneut versuchen oder ein kleineres Modell wählen.</td>
          </tr>
          <tr>
            <td>Bricht ohne Meldung ab</td>
            <td className="unit">Claude Code im Terminal starten und eine kurze Frage stellen. Klappt das, Lumora neu starten und erneut versuchen.</td>
          </tr>
        </tbody>
      </table>
      <p className="hint">
        Claude bekommt dabei nur die Werkzeuge von Lumora: Raum und Songanalyse lesen, Shows schreiben, Bilder der Show prüfen und im Internet recherchieren. Es hat keinen
        Zugriff auf deine Dateien oder die Kommandozeile.
      </p>
    </div>
  );
}
