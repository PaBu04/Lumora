import { lazy, Suspense, useEffect, useState } from "react";
import { api } from "./api";
import { useStore, type Tab } from "./store";
import { Icon } from "./ui";
// views are loaded on demand so the first paint does not wait for three.js
const AiView = lazy(() => import("./views/AiView").then((m) => ({ default: m.AiView })));
const CalibrationView = lazy(() => import("./views/CalibrationView").then((m) => ({ default: m.CalibrationView })));
const DevicesView = lazy(() => import("./views/DevicesView").then((m) => ({ default: m.DevicesView })));
const FixturesView = lazy(() => import("./views/FixturesView").then((m) => ({ default: m.FixturesView })));
const RoomView = lazy(() => import("./views/RoomView").then((m) => ({ default: m.RoomView })));
const ShowsView = lazy(() => import("./views/ShowsView").then((m) => ({ default: m.ShowsView })));
const SongsView = lazy(() => import("./views/SongsView").then((m) => ({ default: m.SongsView })));

const NAV: { id: Tab; label: string; icon: string }[] = [
  { id: "room", label: "Raum", icon: "room" },
  { id: "fixtures", label: "LED-Strips", icon: "strip" },
  { id: "devices", label: "Controller", icon: "device" },
  { id: "calibration", label: "Kalibrierung", icon: "calibrate" },
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

function UndoButtons() {
  const scope = useStore((s) => s.undoScope);
  const past = useStore((s) => s.past.length);
  const future = useStore((s) => s.future.length);
  const undo = useStore((s) => s.undo);
  const redo = useStore((s) => s.redo);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || (e.target as HTMLElement).closest("input, textarea, select")) return;
      const key = e.key.toLowerCase();
      if (useStore.getState().undoScope !== "project") return;
      if (key === "z" && !e.shiftKey) {
        e.preventDefault();
        undo();
      } else if (key === "y" || (key === "z" && e.shiftKey)) {
        e.preventDefault();
        redo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);
  if (scope !== "project") return null;
  return (
    <div className="row" style={{ gap: 4 }}>
      <button className="btn ghost icon" title="Rückgängig (Strg+Z)" disabled={!past} onClick={undo}>
        ↶
      </button>
      <button className="btn ghost icon" title="Wiederholen (Strg+Y)" disabled={!future} onClick={redo}>
        ↷
      </button>
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
      {pb && pb.power.total_requested_ma > 0 && (
        <span
          className={`status-pill${pb.power.total_requested_ma > pb.power.total_ma + 50 ? " live" : ""}`}
          title={pb.power.total_requested_ma > pb.power.total_ma + 50 ? `Strombudget greift: ${(pb.power.total_requested_ma / 1000).toFixed(1)} A angefragt` : "geschätzte Stromaufnahme"}
        >
          ⚡ {(pb.power.total_ma / 1000).toFixed(1)} A
        </span>
      )}
    </div>
  );
}

/** Where frames go: only the 3D preview, or also to the LEDs. */
function ModeSwitch() {
  const mode = useStore((s) => s.playback?.mode);
  const setPlayback = useStore((s) => s.setPlayback);
  const notify = useStore((s) => s.notify);
  if (!mode) return null;
  const set = async (m: "preview" | "live") => {
    try {
      setPlayback(await api.mode(m));
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };
  return (
    <div className="seg mode-switch" role="group" aria-label="Ausgabe">
      <button className={mode === "preview" ? "on" : ""} title="Nur die 3D-Vorschau in der App" onClick={() => set("preview")}>
        Vorschau
      </button>
      <button className={mode === "live" ? "on live" : ""} title="Bilder auch an die WLED-Controller senden" onClick={() => set("live")}>
        <span className="dot" /> Live
      </button>
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
            <i style={{ background: "#ff7a90" }} />
            <i style={{ background: "#6ec6ff" }} />
            <i style={{ background: "#ffd36e" }} />
          </span>
          Light Show Generator
        </div>
        <ProjectSwitcher />
        {project && <UndoButtons />}
        <div className="spacer" />
        {project && <StatusArea />}
        {project && <ModeSwitch />}
      </header>
      <nav className="sidebar">
        {NAV.map((n) => (
          <button key={n.id} className={`nav-btn${tab === n.id ? " active" : ""}`} disabled={!project && n.id !== "ai"} onClick={() => setTab(n.id)}>
            <Icon name={n.icon} />
            {n.label}
          </button>
        ))}
      </nav>
      <main className="main">
        {ready && !project && tab !== "ai" ? (
          <Welcome />
        ) : (
          <Suspense fallback={<div className="welcome hint">Lade…</div>}>
            {tab === "room" && <RoomView />}
            {tab === "fixtures" && <FixturesView />}
            {tab === "devices" && <DevicesView />}
            {tab === "calibration" && <CalibrationView />}
            {tab === "songs" && <SongsView />}
            {tab === "shows" && <ShowsView />}
            {tab === "ai" && <AiView />}
          </Suspense>
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
