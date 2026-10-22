import { useState } from "react";
import { api } from "../api";
import { uid } from "../geometry";
import { useStore } from "../store";
import type { Controller, WledInfo } from "../types";
import { Field, Icon, NumberInput, TextInput } from "../ui";

function OutputSettings() {
  const pb = useStore((s) => s.playback);
  const setPlayback = useStore((s) => s.setPlayback);
  if (!pb) return null;
  const live = pb.mode === "live";
  return (
    <div className="card">
      <div className="row between" style={{ marginBottom: 10 }}>
        <strong>Ausgabe</strong>
        <div className="row">
          <button className={`btn small${!live ? " active" : ""}`} onClick={async () => setPlayback(await api.mode("preview"))}>
            Nur Vorschau
          </button>
          <button className={`btn small${live ? " live" : ""}`} onClick={async () => setPlayback(await api.mode("live"))}>
            ● Live an LEDs
          </button>
        </div>
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
      <Field label="Gamma">
        <NumberInput value={pb.output.gamma} min={1} max={3} step={0.1} onChange={async (gamma) => setPlayback(await api.output({ gamma }))} />
      </Field>
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
        Live sendet die Frames per DDP (UDP 4048) an alle Controller. Audio-Latenz &gt; 0 verzögert das Licht, z. B. für Bluetooth-Lautsprecher.
        {Object.keys(pb.controller_errors).length > 0 && <span style={{ color: "var(--err)" }}> Sendefehler: {Object.entries(pb.controller_errors).map(([h, e]) => `${h}: ${e}`).join("; ")}</span>}
      </p>
    </div>
  );
}

function ControllerCard({ c }: { c: Controller }) {
  const project = useStore((s) => s.project)!;
  const leds = useStore((s) => s.leds);
  const update = useStore((s) => s.updateProject);
  const notify = useStore((s) => s.notify);
  const pb = useStore((s) => s.playback);
  const setPlayback = useStore((s) => s.setPlayback);
  const [info, setInfo] = useState<WledInfo | null>(null);
  const set = (fn: (c: Controller) => void) =>
    update((p) => {
      fn(p.controllers.find((x) => x.id === c.id)!);
      return p;
    });
  const countOf = (fid: string) => leds?.fixtures.find((f) => f.id === fid)?.count ?? 0;
  const used = c.mappings.reduce((m, x) => Math.max(m, x.start + (x.count ?? countOf(x.fixture_id) - x.fixture_offset)), 0);
  const unmapped = project.fixtures.filter((f) => !project.controllers.some((k) => k.mappings.some((m) => m.fixture_id === f.id)));
  const testing = pb?.test;

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
          <button
            className="btn ghost small danger"
            onClick={() => update((p) => ({ ...p, controllers: p.controllers.filter((x) => x.id !== c.id) }))}
          >
            <Icon name="trash" />
          </button>
        </div>
      </div>
      {info && (
        <div className={`banner ${info.error ? "err" : "info"}`}>
          {info.error
            ? `Nicht erreichbar: ${info.error}`
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
        <Field label="DDP-Port">
          <NumberInput integer value={c.port} min={1} max={65535} step={1} onChange={(v) => set((x) => (x.port = v))} />
        </Field>
        <Field label="Latenz (ms)">
          <NumberInput value={c.latency_ms} min={-1000} max={1000} step={5} onChange={(v) => set((x) => (x.latency_ms = v))} />
        </Field>
        <Field label="RGBW">
          <input type="checkbox" checked={c.rgbw} onChange={(e) => set((x) => (x.rgbw = e.target.checked))} />
        </Field>
        <Field label="Pixel belegt">
          <span className="badge">{used}</span>
        </Field>
      </div>
      <h3>Zuordnung</h3>
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
            <tr key={i}>
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
  const notify = useStore((s) => s.notify);
  const error = useStore((s) => s.projectError);
  const pb = useStore((s) => s.playback);
  const setPlayback = useStore((s) => s.setPlayback);
  const [found, setFound] = useState<WledInfo[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [host, setHost] = useState("");
  if (!project) return null;

  const addController = (info: WledInfo) => {
    const hostOnly = info.host;
    update((p) => ({
      ...p,
      controllers: [
        ...p.controllers,
        { id: uid(), name: info.name || hostOnly, host: hostOnly, port: 4048, mac: info.mac ?? null, rgbw: !!info.rgbw, latency_ms: 0, mappings: [] },
      ],
    }));
    notify(`Controller „${info.name}" hinzugefügt`, "success");
  };
  const known = new Set(project.controllers.map((c) => c.host.split(":")[0]));

  return (
    <div className="view split-right">
      <div className="pane">
        <div className="row between">
          <h2>Controller (WLED)</h2>
          {pb?.test && (
            <button className="btn small active" onClick={async () => setPlayback(await api.test(false, null))}>
              Testmuster beenden
            </button>
          )}
        </div>
        {error && <div className="banner err">{error}</div>}
        {project.controllers.length === 0 && (
          <p className="hint">
            Noch kein Controller. Suche WLED-Geräte im Netzwerk oder gib eine IP-Adresse ein. Danach Strips zuordnen: Start = erstes Pixel des
            Strips am Ausgang des Controllers.
          </p>
        )}
        {project.controllers.map((c) => (
          <ControllerCard key={c.id} c={c} />
        ))}
      </div>
      <div className="pane">
        <OutputSettings />
        <div className="card">
          <strong>Geräte finden</strong>
          <p className="hint">Sucht per mDNS nach WLED-Controllern im lokalen Netz.</p>
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
    </div>
  );
}
