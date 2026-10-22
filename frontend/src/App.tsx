import { useEffect, useState } from "react";
import { useStore, type Tab } from "./store";
import { Icon } from "./ui";
import { AiView } from "./views/AiView";
import { DevicesView } from "./views/DevicesView";
import { FixturesView } from "./views/FixturesView";
import { RoomView } from "./views/RoomView";
import { ShowsView } from "./views/ShowsView";
import { SongsView } from "./views/SongsView";

const NAV: { id: Tab; label: string; icon: string }[] = [
  { id: "room", label: "Raum", icon: "room" },
  { id: "fixtures", label: "LED-Strips", icon: "strip" },
  { id: "devices", label: "Controller", icon: "device" },
  { id: "songs", label: "Songs", icon: "music" },
  { id: "shows", label: "Shows", icon: "show" },
  { id: "ai", label: "KI / MCP", icon: "ai" },
];

function Welcome() {
  const create = useStore((s) => s.createProject);
  const [name, setName] = useState("Mein Raum");
  return (
    <div className="welcome">
      <div className="card">
        <h2>Willkommen</h2>
        <p className="hint">Lege ein Projekt für deinen Raum an. Danach zeichnest du den Grundriss, platzierst LED-Strips und verbindest WLED-Controller.</p>
        <div className="row">
          <div className="grow">
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && create(name)} />
          </div>
          <button className="btn primary" onClick={() => create(name)}>
            Projekt anlegen
          </button>
        </div>
      </div>
    </div>
  );
}

function ProjectSwitcher() {
  const projects = useStore((s) => s.projects);
  const slug = useStore((s) => s.slug);
  const open = useStore((s) => s.openProject);
  const create = useStore((s) => s.createProject);
  if (!slug) return null;
  return (
    <div className="row">
      <select
        value={slug}
        style={{ width: 200 }}
        onChange={async (e) => {
          if (e.target.value === "__new__") {
            const name = prompt("Name des neuen Projekts", "Neuer Raum");
            if (name) await create(name);
            return;
          }
          await open(e.target.value);
        }}
      >
        {projects.map((p) => (
          <option key={p.slug} value={p.slug}>
            {p.name}
          </option>
        ))}
        <option value="__new__">+ Neues Projekt…</option>
      </select>
    </div>
  );
}

function StatusArea() {
  const pb = useStore((s) => s.playback);
  const saving = useStore((s) => s.saving);
  const error = useStore((s) => s.projectError);
  const leds = useStore((s) => s.leds);
  return (
    <div className="row">
      {error ? (
        <span className="status-pill live" title={error}>
          Nicht gespeichert
        </span>
      ) : (
        <span className="status-pill">{saving ? "Speichert…" : "Gespeichert"}</span>
      )}
      {leds && <span className="status-pill">{leds.count} LEDs</span>}
      {pb?.playing && <span className="status-pill">▶ {pb.show_name}</span>}
      {pb?.test && <span className="status-pill">Testmuster aktiv</span>}
      <span className={`status-pill${pb?.mode === "live" ? " live" : ""}`}>
        <span className="dot" /> {pb?.mode === "live" ? "LIVE" : "Vorschau"}
      </span>
    </div>
  );
}

export function App() {
  const tab = useStore((s) => s.tab);
  const setTab = useStore((s) => s.setTab);
  const project = useStore((s) => s.project);
  const init = useStore((s) => s.init);
  const toasts = useStore((s) => s.toasts);
  const dismiss = useStore((s) => s.dismiss);
  const notify = useStore((s) => s.notify);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    init()
      .catch((e) => notify(`Backend nicht erreichbar: ${(e as Error).message}`, "error"))
      .finally(() => setReady(true));
  }, [init, notify]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="logo">
          <span className="dots">
            <i style={{ background: "#ff2d95" }} />
            <i style={{ background: "#00d4ff" }} />
            <i style={{ background: "#ffd400" }} />
          </span>
          Light Show Generator
        </div>
        <ProjectSwitcher />
        <div className="spacer" />
        {project && <StatusArea />}
      </header>
      <nav className="sidebar">
        {NAV.map((n) => (
          <button key={n.id} className={`nav-btn${tab === n.id ? " active" : ""}`} disabled={!project && n.id !== "ai"} onClick={() => setTab(n.id)}>
            <Icon name={n.icon} />
            {n.label}
          </button>
        ))}
        <div className="foot">
          WS2812B · SK6812
          <br />
          WLED über DDP
        </div>
      </nav>
      <main className="main">
        {ready && !project && tab !== "ai" ? (
          <Welcome />
        ) : (
          <>
            {tab === "room" && <RoomView />}
            {tab === "fixtures" && <FixturesView />}
            {tab === "devices" && <DevicesView />}
            {tab === "songs" && <SongsView />}
            {tab === "shows" && <ShowsView />}
            {tab === "ai" && <AiView />}
          </>
        )}
      </main>
      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`} onClick={() => dismiss(t.id)}>
            {t.message}
          </div>
        ))}
      </div>
    </div>
  );
}
