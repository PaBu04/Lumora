import { Panes } from "../components/Panes";
import { Scene3D } from "../three/Scene3D";
import { useState } from "react";
import { api } from "../api";
import { uid } from "../geometry";
import { useStore } from "../store";
import type { Controller, SpeedTestResult, WledInfo } from "../types";
import { EmptyState, Expert, Field, Icon, NumberInput, TextInput } from "../ui";
import { Help } from "../components/Help";
import { friendly } from "../errors";

function StatusLine({ id }: { id: string }) {
  const st = useStore((s) => s.playback?.controller_status?.[id]);
  const link = useStore((s) => s.playback?.links?.[id]);
  const live = useStore((s) => s.playback?.mode === "live");
  const measuring = useStore((s) => s.playback?.speed_testing?.includes(id));
  if (!st) return <p className="hint">Status wird abgefragt…</p>;
  if (!st.ok) return <div className="banner err">WLED {friendly(st.error ?? "nicht erreichbar")}</div>;
  const i = st.info!;
  return (
    <div style={{ marginBottom: 10 }}>
      <div className="row">
        <span className="badge ok">verbunden</span>
        {i.version && <span className="badge">WLED {i.version}</span>}
        {i.arch && <span className="badge">{String(i.arch).toUpperCase()}</span>}
        {measuring && <span className="badge warn">Messung läuft</span>}
        {live && link && !measuring && (
          <span className="badge info" title={`Takt für diesen Controller: ${link.rate} FPS. Unveränderte Bilder gehen nur als Keep-alive raus.`}>
            sendet {Math.round(link.sent_fps)} FPS
          </span>
        )}
        {i.live && (
          <span className="badge info" title="von WLED gemeldete Bildrate der LEDs">
            WLED zeigt {i.fps ?? "?"} FPS
          </span>
        )}
        {st.config?.max_fps ? (
          <span className="badge" title="geschätzt aus LED-Anzahl und Datenpins in der WLED-Konfiguration">
            max. ≈ {Math.round(st.config.max_fps)} FPS
          </span>
        ) : null}
        {i.rssi !== undefined && i.rssi !== null && (
          <span className={`badge ${i.rssi < -75 ? "warn" : ""}`}>
            WLAN {i.rssi} dBm{i.signal ? ` (${i.signal} %)` : ""}
          </span>
        )}
      </div>
      {(st.hints ?? []).map((h) => (
        <div key={h} className="banner info" style={{ marginTop: 6, marginBottom: 0 }}>
          {h}
        </div>
      ))}
      {st.warnings.map((w) => (
        <div key={w} className="banner err" style={{ marginTop: 6, marginBottom: 0 }}>
          {w}
        </div>
      ))}
    </div>
  );
}

const amps = (ma: number) => `${(ma / 1000).toFixed(1)} A`;

function PowerSupply() {
  const project = useStore((s) => s.project)!;
  const update = useStore((s) => s.updateProject);
  const pb = useStore((s) => s.playback);
  const p = pb?.power;
  return (
    <>
      <Field label="Netzteil gesamt (A)" help={<Help id="power" />}>
        <input
          type="number"
          min={0.1}
          step={0.5}
          placeholder="unbegrenzt"
          value={project.power.total_budget_ma ? project.power.total_budget_ma / 1000 : ""}
          onChange={(e) =>
            update((pr) => ({ ...pr, power: { ...pr.power, total_budget_ma: e.target.value === "" ? null : Math.max(100, +e.target.value * 1000) } }))
          }
        />
      </Field>
      {p && (
        <Field label="Strom jetzt">
          <span className={`badge ${p.total_budget_ma && p.total_requested_ma > p.total_budget_ma ? "warn" : "info"}`}>
            {amps(p.total_ma)}
            {p.total_requested_ma > p.total_ma + 50 && ` (gedrosselt von ${amps(p.total_requested_ma)})`}
          </span>
          {p.peak_ma.total !== undefined && <span className="unit"> Spitze {amps(p.peak_ma.total)}</span>}
        </Field>
      )}
    </>
  );
}

function OutputSettings() {
  const pb = useStore((s) => s.playback);
  const setPlayback = useStore((s) => s.setPlayback);
  if (!pb) return null;
  return (
    <div className="card">
      <div style={{ marginBottom: 10 }}>
        <strong>Ausgabe</strong>
      </div>
      <Field label="Helligkeit">
        <div className="row">
          <input
            type="range"
            className="grow"
            min={0}
            max={1}
            step={0.01}
            value={pb.output.brightness}
            onChange={async (e) => setPlayback(await api.output({ brightness: +e.target.value }))}
          />
          <span className="unit" style={{ width: 36 }}>
            {Math.round(pb.output.brightness * 100)}%
          </span>
        </div>
      </Field>
      <PowerSupply />
      <Field label="Audio-Latenz (ms)">
        <NumberInput
          value={pb.output.audio_latency_ms}
          min={-1000}
          max={2000}
          step={10}
          onChange={async (audio_latency_ms) => setPlayback(await api.output({ audio_latency_ms }))}
        />
      </Field>
      <p className="hint">
        Audio-Latenz verzögert das Licht, z. B. bei Bluetooth-Lautsprechern. Ist ein Strombudget gesetzt, wird automatisch gedimmt.
        {Object.keys(pb.controller_errors).length > 0 && <span style={{ color: "var(--err)" }}> Sendefehler: {Object.entries(pb.controller_errors).map(([h, e]) => `${h}: ${e}`).join("; ")}</span>}
      </p>
    </div>
  );
}

function ControllerCard({ c, onHover }: { c: Controller; onHover: (fixture: string | null) => void }) {
  const project = useStore((s) => s.project)!;
  const leds = useStore((s) => s.leds);
  const update = useStore((s) => s.updateProject);
  const notify = useStore((s) => s.notify);
  const pb = useStore((s) => s.playback);
  const setPlayback = useStore((s) => s.setPlayback);
  const [info, setInfo] = useState<WledInfo | null>(null);
  const [speed, setSpeed] = useState<SpeedTestResult | null>(null);
  const [measuring, setMeasuring] = useState(false);
  const status = pb?.controller_status?.[c.id];
  const autoRate = status?.rate_auto ? status.rate : undefined;
  const set = (fn: (c: Controller) => void) =>
    update((p) => {
      fn(p.controllers.find((x) => x.id === c.id)!);
      return p;
    });
  const countOf = (fid: string) => leds?.fixtures.find((f) => f.id === fid)?.count ?? 0;
  const used = c.mappings.reduce((m, x) => Math.max(m, x.start + (x.count ?? countOf(x.fixture_id) - x.fixture_offset)), 0);
  const unmapped = project.fixtures.filter((f) => !project.controllers.some((k) => k.mappings.some((m) => m.fixture_id === f.id)));
  const testing = pb?.test;
  const power = pb?.power.controllers[c.id];

  const refresh = async () => {
    try {
      const i = await api.deviceInfo(c.host);
      setInfo(i);
      if (i.rgbw !== undefined && i.rgbw !== c.rgbw) set((x) => (x.rgbw = !!i.rgbw));
    } catch (e) {
      setInfo({ host: c.host, name: c.name, error: (e as Error).message });
    }
  };

  return (
    <div className="card">
      <div className="row between" style={{ marginBottom: 10 }}>
        <div className="row">
          <Icon name="device" />
          <strong>{c.name}</strong>
          <span className="meta unit">{c.host}</span>
        </div>
        <div className="row">
          <button className="btn small" onClick={refresh}>
            WLED abfragen
          </button>
          <Expert>
          <button
            className="btn small"
            disabled={measuring || used === 0}
            title="Schickt etwa 6 Sekunden ein Testmuster und misst, wie viele Bilder pro Sekunde der Controller wirklich zeigt"
            onClick={async () => {
              setMeasuring(true);
              setSpeed(null);
              try {
                setSpeed(await api.speedTest(c.id));
              } catch (e) {
                notify((e as Error).message, "error");
              } finally {
                setMeasuring(false);
              }
            }}
          >
            {measuring ? "Misst… (6 s)" : "Geschwindigkeit messen"}
          </button>
          </Expert>
          <button
            className="btn ghost small danger"
            onClick={() => update((p) => ({ ...p, controllers: p.controllers.filter((x) => x.id !== c.id) }))}
          >
            <Icon name="trash" />
          </button>
        </div>
      </div>
      <StatusLine id={c.id} />
      {speed && (
        <div className="banner info speed-result">
          <div>
            Zeigt höchstens <strong>{Math.round(speed.measured_fps)} FPS</strong>
            {speed.estimated_fps ? ` (geschätzt ${Math.round(speed.estimated_fps)})` : ""}. Bei {speed.test_fps} gesendeten FPS kamen{" "}
            {speed.shown_fps} an{speed.loss_pct ? ` – ${speed.loss_pct} % gingen unterwegs verloren (WLAN prüfen)` : ", nichts ging verloren"}.
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <span>Empfohlene Bildrate: {speed.recommended_fps} FPS</span>
            <button className="btn primary small" onClick={() => set((x) => (x.max_fps = speed.recommended_fps))}>
              Übernehmen
            </button>
            {c.max_fps != null && (
              <button className="btn ghost small" onClick={() => set((x) => (x.max_fps = null))}>
                Automatisch
              </button>
            )}
          </div>
        </div>
      )}
      {info && (
        <div className={`banner ${info.error ? "err" : "info"}`}>
          {info.error
            ? `Nicht erreichbar: ${friendly(info.error)}`
            : `${info.name} · WLED ${info.version ?? "?"} · ${info.led_count} LEDs konfiguriert · ${info.rgbw ? "RGBW" : "RGB"}`}
          {info.led_count !== undefined && used > info.led_count && (
            <div>Achtung: Zuordnung nutzt {used} Pixel, in WLED sind nur {info.led_count} konfiguriert.</div>
          )}
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 12px" }}>
        <Field label="Name">
          <TextInput value={c.name} onChange={(v) => set((x) => (x.name = v))} />
        </Field>
        <Field label="Host / IP">
          <TextInput value={c.host} onChange={(v) => set((x) => (x.host = v.trim()))} />
        </Field>
        <Field label="RGBW">
          <input type="checkbox" checked={c.rgbw} onChange={(e) => set((x) => (x.rgbw = e.target.checked))} />
        </Field>
        <Field label="Pixel belegt">
          <span className="badge">{used}</span>
        </Field>
        <Field label="Budget (A)" help={<Help id="power" />}>
          <input
            type="number"
            min={0.1}
            step={0.5}
            placeholder="unbegrenzt"
            value={c.budget_ma ? c.budget_ma / 1000 : ""}
            onChange={(e) => set((x) => (x.budget_ma = e.target.value === "" ? null : Math.max(100, +e.target.value * 1000)))}
          />
        </Field>
        <Expert>
        <Field label="Bildrate (FPS)" help={<Help id="fps" />}>
          <input
            type="number"
            min={5}
            max={120}
            step={1}
            placeholder={autoRate ? `automatisch (${autoRate})` : "automatisch"}
            title="Wie oft dieser Controller ein neues Bild bekommt. Leer = automatisch aus der LED-Konfiguration in WLED."
            value={c.max_fps ?? ""}
            onChange={(e) => set((x) => (x.max_fps = e.target.value === "" ? null : Math.min(120, Math.max(5, +e.target.value))))}
          />
        </Field>
        </Expert>
        <Field label="Strom jetzt">
          {power ? (
            <span className={`badge ${power.scale < 1 ? "warn" : "info"}`} title="geschätzt aus den gesendeten PWM-Werten">
              {amps(power.ma)}
              {power.scale < 1 && ` · gedrosselt auf ${Math.round(power.scale * 100)} %`}
            </span>
          ) : (
            <span className="unit">–</span>
          )}
        </Field>
      </div>
      <details className="more">
        <summary>Erweitert</summary>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 12px", marginTop: 8 }}>
          <Field label="Latenz (ms)">
            <NumberInput value={c.latency_ms} min={-1000} max={1000} step={5} onChange={(v) => set((x) => (x.latency_ms = v))} />
          </Field>
          <Field label="DDP-Port">
            <NumberInput integer value={c.port} min={1} max={65535} step={1} onChange={(v) => set((x) => (x.port = v))} />
          </Field>
        </div>
      </details>
      <h3>
        Zuordnung <Help id="mapping" />
      </h3>
      <table className="grid">
        <thead>
          <tr>
            <th>Strip</th>
            <th title="erstes Pixel am Controller">Start</th>
            <th title="erste LED des Strips">Offset</th>
            <th title="leer = Rest des Strips">Anzahl</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {c.mappings.map((m, i) => (
            <tr key={i} onMouseEnter={() => onHover(m.fixture_id)} onMouseLeave={() => onHover(null)}>
              <td>
                <select value={m.fixture_id} onChange={(e) => set((x) => (x.mappings[i].fixture_id = e.target.value))}>
                  {project.fixtures.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name} ({countOf(f.id)})
                    </option>
                  ))}
                </select>
              </td>
              <td style={{ width: 80 }}>
                <NumberInput integer value={m.start} min={0} step={1} onChange={(v) => set((x) => (x.mappings[i].start = v))} />
              </td>
              <td style={{ width: 70 }}>
                <NumberInput integer value={m.fixture_offset} min={0} step={1} onChange={(v) => set((x) => (x.mappings[i].fixture_offset = v))} />
              </td>
              <td style={{ width: 80 }}>
                <input
                  type="number"
                  placeholder={String(countOf(m.fixture_id) - m.fixture_offset)}
                  value={m.count ?? ""}
                  onChange={(e) => set((x) => (x.mappings[i].count = e.target.value === "" ? null : Math.max(1, Math.round(+e.target.value))))}
                />
              </td>
              <td className="row" style={{ flexWrap: "nowrap" }}>
                <button
                  className={`btn small${testing?.fixture === m.fixture_id ? " active" : ""}`}
                  title="Testmuster: Anfang grün, Ende rot, Rest blinkt blau"
                  onClick={async () => setPlayback(await api.test(testing?.fixture !== m.fixture_id, m.fixture_id))}
                >
                  Test
                </button>
                <button className="btn ghost small" onClick={() => set((x) => x.mappings.splice(i, 1))}>
                  ✕
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row" style={{ marginTop: 8 }}>
        <button
          className="btn small"
          disabled={project.fixtures.length === 0}
          onClick={() =>
            set((x) => {
              const f = unmapped[0] ?? project.fixtures[0];
              x.mappings.push({ fixture_id: f.id, start: used, fixture_offset: 0, count: null });
            })
          }
        >
          <Icon name="plus" /> Strip zuordnen
        </button>
        <button
          className="btn small"
          disabled={c.mappings.length === 0}
          title="Startpixel so setzen, dass die Strips direkt hintereinander hängen"
          onClick={() =>
            set((x) => {
              let s = 0;
              for (const m of x.mappings) {
                m.start = s;
                s += m.count ?? countOf(m.fixture_id) - m.fixture_offset;
              }
            })
          }
        >
          Hintereinander verketten
        </button>
        {unmapped.length > 0 && (
          <button
            className="btn small"
            onClick={() => {
              set((x) => {
                let s = used;
                for (const f of unmapped) {
                  x.mappings.push({ fixture_id: f.id, start: s, fixture_offset: 0, count: null });
                  s += countOf(f.id);
                }
              });
              notify(`${unmapped.length} Strip(s) zugeordnet`, "success");
            }}
          >
            Alle freien Strips anhängen
          </button>
        )}
      </div>
    </div>
  );
}

export function DevicesView() {
  const project = useStore((s) => s.project);
  const update = useStore((s) => s.updateProject);
  const setTab = useStore((s) => s.setTab);
  const notify = useStore((s) => s.notify);
  const error = useStore((s) => s.projectError);
  const pb = useStore((s) => s.playback);
  const setPlayback = useStore((s) => s.setPlayback);
  const [found, setFound] = useState<WledInfo[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [host, setHost] = useState("");
  const [hover, setHover] = useState<string | null>(null);
  if (!project) return null;

  const addController = (info: WledInfo) => {
    const hostOnly = info.host;
    update((p) => ({
      ...p,
      controllers: [
        ...p.controllers,
        { id: uid(), name: info.name || hostOnly, host: hostOnly, port: 4048, mac: info.mac ?? null, rgbw: !!info.rgbw, latency_ms: 0, budget_ma: null, max_fps: null, mappings: [] },
      ],
    }));
    notify(`Controller „${info.name}" hinzugefügt`, "success");
  };
  const known = new Set(project.controllers.map((c) => c.host.split(":")[0]));

  return (
    <Panes id="devices" sizes={[560, null, 340]} className="view">
      <div className="pane">
        <div className="row between">
          <h2>
            Controller (WLED) <Help id="controller" />
          </h2>
          {pb?.test && (
            <button className="btn small active" onClick={async () => setPlayback(await api.test(false, null))}>
              Testmuster beenden
            </button>
          )}
        </div>
        {error && <div className="banner err">{error}</div>}
        {project.controllers.length === 0 && (
          <EmptyState
            title="Noch kein Controller"
            actions={
              <button
                className="btn small"
                onClick={() => {
                  useStore.getState().markGuide("controller");
                  setTab("songs");
                }}
              >
                Ohne Hardware weiter zu „Songs“
              </button>
            }
          >
            Rechts „Netzwerk durchsuchen“ findet WLED-Geräte im Heimnetz, oder du gibst die IP-Adresse ein. Danach ordnest du die Strips zu:
            Start = erstes Pixel des Strips am Ausgang des Controllers. Ohne Hardware laufen alle Shows in der 3D-Vorschau.
          </EmptyState>
        )}
        {project.controllers.map((c) => (
          <ControllerCard key={c.id} c={c} onHover={setHover} />
        ))}
      </div>
      <div className="pane flush">
        <div className="canvas-wrap">
          <Scene3D highlight={hover ?? pb?.test?.fixture ?? null} />
        </div>
        <div className="overlay">
          <span className="badge">{pb?.test ? "Testmuster: grün = Anfang, rot = Ende des Strips" : "Maus über eine Zuordnung zeigt den Strip im Raum"}</span>
        </div>
      </div>
      <div className="pane">
        <OutputSettings />
        <div className="card">
          <strong>Geräte finden</strong>
          <p className="hint">Sucht WLED-Controller im Heimnetz.</p>
          <button
            className="btn primary"
            disabled={searching}
            onClick={async () => {
              setSearching(true);
              try {
                setFound(await api.discover(3));
              } catch (e) {
                notify((e as Error).message, "error");
              }
              setSearching(false);
            }}
          >
            {searching ? "Suche läuft…" : "Netzwerk durchsuchen"}
          </button>
          {found && (
            <div className="list" style={{ marginTop: 10 }}>
              {found.length === 0 && <p className="hint">Keine Geräte gefunden.</p>}
              {found.map((d) => (
                <div key={d.host} className="list-item">
                  <div className="grow">
                    <div>{d.name}</div>
                    <div className="meta">
                      {d.host}
                      {d.led_count !== undefined && ` · ${d.led_count} LEDs · ${d.rgbw ? "RGBW" : "RGB"}`}
                      {d.error && ` · ${d.error}`}
                    </div>
                  </div>
                  <button className="btn small" disabled={known.has(d.host.split(":")[0])} onClick={() => addController(d)}>
                    {known.has(d.host.split(":")[0]) ? "vorhanden" : "Hinzufügen"}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="card">
          <strong>Manuell hinzufügen</strong>
          <div className="row" style={{ marginTop: 8 }}>
            <div className="grow">
              <input type="text" placeholder="192.168.1.50" value={host} onChange={(e) => setHost(e.target.value)} />
            </div>
            <button
              className="btn"
              disabled={!host.trim()}
              onClick={async () => {
                try {
                  addController(await api.deviceInfo(host.trim()));
                } catch (e) {
                  notify(`${(e as Error).message} – Controller wird trotzdem angelegt`, "error");
                  addController({ host: host.trim(), name: host.trim() });
                }
                setHost("");
              }}
            >
              Hinzufügen
            </button>
          </div>
        </div>
      </div>
    </Panes>
  );
}
