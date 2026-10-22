import { useState } from "react";
import { makePreset, moveItem, PRESETS, round, wallLength, type PresetId } from "../geometry";
import { useStore } from "../store";
import { MOVE_ALL, Scene3D } from "../three/Scene3D";
import type { Fixture, Geometry, LedType, Project, Vec3 } from "../types";
import { Field, Icon, NumberInput, TextInput, Vec3Input } from "../ui";

const TYPE_LABEL: Record<Geometry["type"], string> = {
  polyline: "Linie",
  bezier: "Kurve",
  arc: "Bogen",
  circle: "Kreis",
  heart: "Herz",
  matrix: "Matrix",
};

const NORMALS: { label: string; v: Vec3 }[] = [
  { label: "waagrecht (Decke/Boden)", v: [0, 0, 1] },
  { label: "senkrecht, Wand in x-Richtung", v: [0, 1, 0] },
  { label: "senkrecht, Wand in y-Richtung", v: [1, 0, 0] },
];

function GeometryEditor({ f, onChange }: { f: Fixture; onChange: (g: Geometry) => void }) {
  const g = f.geometry;
  const selectedPoint = useStore((s) => s.selectedPoint);
  const select = useStore((s) => s.selectFixture);
  const [drag, setDrag] = useState<{ from: number; over: number } | null>(null);
  switch (g.type) {
    case "polyline":
    case "bezier": {
      const isBezier = g.type === "bezier";
      // bezier: anchors and their control points move together, so only polylines are reordered
      const sortable = !isBezier;
      return (
        <>
          <table className="grid points">
            <thead>
              <tr>
                <th>#</th>
                <th>x / y / z (m)</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {g.points.map((p, i) => (
                <tr
                  key={i}
                  className={`${selectedPoint === i ? "sel" : ""}${drag && drag.over === i && drag.from !== i ? (drag.from < i ? " drop-below" : " drop-above") : ""}`}
                  onClick={() => select(f.id, i)}
                  onDragOver={(e) => {
                    if (!drag) return;
                    e.preventDefault();
                    if (drag.over !== i) setDrag({ ...drag, over: i });
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    if (drag && drag.from !== i) onChange({ ...g, points: moveItem(g.points, drag.from, i) });
                    setDrag(null);
                  }}
                >
                  <td className="unit">
                    {sortable ? (
                      <span
                        className="grip"
                        draggable
                        title="Ziehen zum Umsortieren"
                        onDragStart={(e) => {
                          e.dataTransfer.effectAllowed = "move";
                          e.dataTransfer.setData("text/plain", String(i));
                          setDrag({ from: i, over: i });
                        }}
                        onDragEnd={() => setDrag(null)}
                      >
                        ⠿ {i + 1}
                      </span>
                    ) : i % 3 === 0 ? (
                      `P${i / 3}`
                    ) : (
                      "c"
                    )}
                  </td>
                  <td>
                    <Vec3Input
                      value={p}
                      onChange={(v) => {
                        const points = g.points.slice();
                        points[i] = v;
                        onChange({ ...g, points });
                      }}
                    />
                  </td>
                  <td>
                    {!isBezier && (
                      <button
                        className="btn ghost small"
                        disabled={g.points.length <= 2}
                        onClick={(e) => {
                          e.stopPropagation();
                          onChange({ ...g, points: g.points.filter((_, j) => j !== i) });
                        }}
                      >
                        ✕
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row" style={{ marginTop: 6 }}>
            <button
              className="btn small"
              onClick={() => {
                const last = g.points[g.points.length - 1];
                const prev = g.points[g.points.length - 2];
                const d = [last[0] - prev[0], last[1] - prev[1], last[2] - prev[2]];
                if (isBezier) {
                  const c1: Vec3 = [round(last[0] + d[0]), round(last[1] + d[1]), round(last[2] + d[2])];
                  const end: Vec3 = [round(last[0] + 2 * d[0]), round(last[1] + 2 * d[1]), round(last[2])];
                  onChange({ ...g, points: [...g.points, c1, [round(end[0] - d[0] * 0.5), round(end[1] - d[1] * 0.5), end[2]], end] });
                } else {
                  onChange({ ...g, points: [...g.points, [round(last[0] + d[0] * 0.5), round(last[1] + d[1] * 0.5), last[2]]] });
                }
              }}
            >
              <Icon name="plus" /> {isBezier ? "Segment" : "Punkt"}
            </button>
          </div>
        </>
      );
    }
    case "arc":
    case "circle":
      return (
        <>
          <Field label="Mittelpunkt">
            <Vec3Input value={g.center} onChange={(center) => onChange({ ...g, center })} />
          </Field>
          <Field label="Radius (m)">
            <NumberInput value={g.radius} min={0.05} step={0.05} onChange={(radius) => onChange({ ...g, radius })} />
          </Field>
          <Field label="Ebene">
            <select
              value={NORMALS.findIndex((n) => n.v.every((x, i) => Math.abs(Math.abs(x) - Math.abs(g.normal[i])) < 1e-6))}
              onChange={(e) => onChange({ ...g, normal: NORMALS[+e.target.value].v, reference: null })}
            >
              <option value={-1} disabled>
                benutzerdefiniert
              </option>
              {NORMALS.map((n, i) => (
                <option key={i} value={i}>
                  {n.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Start (°)">
            <NumberInput value={g.start_deg} step={5} onChange={(start_deg) => onChange({ ...g, start_deg })} />
          </Field>
          {g.type === "arc" && (
            <Field label="Winkel (°)">
              <NumberInput value={g.sweep_deg} step={5} min={-360} max={360} onChange={(sweep_deg) => sweep_deg !== 0 && onChange({ ...g, sweep_deg })} />
            </Field>
          )}
        </>
      );
    case "heart":
      return (
        <>
          <Field label="Mittelpunkt">
            <Vec3Input value={g.center} onChange={(center) => onChange({ ...g, center })} />
          </Field>
          <Field label="Breite (m)">
            <NumberInput value={g.size} min={0.05} step={0.05} onChange={(size) => onChange({ ...g, size })} />
          </Field>
          <Field label="Ebene">
            <select
              value={NORMALS.findIndex((n) => n.v.every((x, i) => Math.abs(Math.abs(x) - Math.abs(g.normal[i])) < 1e-6))}
              onChange={(e) => onChange({ ...g, normal: NORMALS[+e.target.value].v, reference: null })}
            >
              <option value={-1} disabled>
                benutzerdefiniert
              </option>
              {NORMALS.map((n, i) => (
                <option key={i} value={i}>
                  {n.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Drehung (°)">
            <div className="row" style={{ flexWrap: "nowrap" }}>
              <input
                type="range"
                className="grow"
                min={-180}
                max={180}
                step={5}
                value={g.rotate_deg}
                onChange={(e) => onChange({ ...g, rotate_deg: +e.target.value })}
              />
              <div style={{ width: 72, flex: "none" }}>
                <NumberInput value={g.rotate_deg} step={5} min={-180} max={180} onChange={(rotate_deg) => onChange({ ...g, rotate_deg })} />
              </div>
            </div>
          </Field>
          <p className="hint">Die erste LED sitzt an der Spitze. „umgekehrt“ dreht die Laufrichtung.</p>
        </>
      );
    case "matrix":
      return (
        <>
          <Field label="Ursprung (LED 1)">
            <Vec3Input value={g.origin} onChange={(origin) => onChange({ ...g, origin })} />
          </Field>
          <Field label="Spalten-Richtung">
            <Vec3Input value={g.col_dir} step={0.1} onChange={(col_dir) => onChange({ ...g, col_dir })} />
          </Field>
          <Field label="Zeilen-Richtung">
            <Vec3Input value={g.row_dir} step={0.1} onChange={(row_dir) => onChange({ ...g, row_dir })} />
          </Field>
          <Field label="Spalten × Zeilen">
            <div className="row">
              <div className="grow">
                <NumberInput integer value={g.cols} min={1} max={256} step={1} onChange={(cols) => onChange({ ...g, cols })} />
              </div>
              <span className="unit">×</span>
              <div className="grow">
                <NumberInput integer value={g.rows} min={1} max={256} step={1} onChange={(rows) => onChange({ ...g, rows })} />
              </div>
            </div>
          </Field>
          <Field label="LED-Abstand (mm)">
            <NumberInput value={round(g.pitch * 1000, 2)} min={1} step={1} onChange={(v) => onChange({ ...g, pitch: v / 1000 })} />
          </Field>
          <Field label="Verkabelung">
            <div className="row">
              <label className="row">
                <input type="checkbox" checked={g.serpentine} onChange={(e) => onChange({ ...g, serpentine: e.target.checked })} /> Schlange
              </label>
              <label className="row">
                <input type="checkbox" checked={g.column_major} onChange={(e) => onChange({ ...g, column_major: e.target.checked })} /> spaltenweise
              </label>
            </div>
          </Field>
        </>
      );
  }
}

function FixtureEditor({ f, project }: { f: Fixture; project: Project }) {
  const update = useStore((s) => s.updateProject);
  const select = useStore((s) => s.selectFixture);
  const leds = useStore((s) => s.leds);
  const selectedPoint = useStore((s) => s.selectedPoint);
  const info = leds?.fixtures.find((x) => x.id === f.id);
  const set = (fn: (f: Fixture) => void) =>
    update((p) => {
      fn(p.fixtures.find((x) => x.id === f.id)!);
      return p;
    });
  const isMatrix = f.geometry.type === "matrix";
  return (
    <div className="card selected">
      <div className="row between" style={{ marginBottom: 10 }}>
        <strong>{TYPE_LABEL[f.geometry.type]}</strong>
        <div className="row">
          {info && <span className="badge info">{info.count} LEDs</span>}
          {info && !isMatrix && <span className="badge">{info.length.toFixed(2)} m</span>}
        </div>
      </div>
      <Field label="Name">
        <TextInput value={f.name} onChange={(name) => set((x) => (x.name = name))} />
      </Field>
      <Field label="LED-Typ">
        <select value={f.led_type} onChange={(e) => set((x) => (x.led_type = e.target.value as LedType))}>
          <option value="ws2812b">WS2812B (RGB)</option>
          <option value="sk6812">SK6812 (RGB)</option>
          <option value="sk6812_rgbw">SK6812 RGBW</option>
        </select>
      </Field>
      {!isMatrix && (
        <>
          <Field label="LEDs pro Meter">
            <select
              value={f.led_count === null ? String(f.leds_per_meter) : "count"}
              onChange={(e) =>
                set((x) => {
                  if (e.target.value === "count") x.led_count = info?.count ?? 60;
                  else {
                    x.led_count = null;
                    x.leds_per_meter = +e.target.value;
                  }
                })
              }
            >
              {[30, 60, 74, 96, 144].map((d) => (
                <option key={d} value={d}>
                  {d} LEDs/m
                </option>
              ))}
              {![30, 60, 74, 96, 144].includes(f.leds_per_meter) && f.led_count === null && <option value={f.leds_per_meter}>{f.leds_per_meter} LEDs/m</option>}
              <option value="count">feste Anzahl…</option>
            </select>
          </Field>
          {f.led_count !== null && (
            <Field label="Anzahl LEDs">
              <NumberInput integer value={f.led_count} min={1} max={5000} step={1} onChange={(v) => set((x) => (x.led_count = v))} />
            </Field>
          )}
          <Field label="Datenrichtung">
            <label className="row">
              <input type="checkbox" checked={f.reverse} onChange={(e) => set((x) => (x.reverse = e.target.checked))} /> umgekehrt
            </label>
          </Field>
        </>
      )}
      <Field label="Tags">
        <TextInput
          value={f.tags.join(", ")}
          placeholder="z. B. ceiling, wall"
          onChange={(v) =>
            set(
              (x) =>
                (x.tags = v
                  .split(",")
                  .map((t) => t.trim().toLowerCase())
                  .filter(Boolean)),
            )
          }
        />
      </Field>
      <div className="row between" style={{ margin: "18px 0 8px" }}>
        <h3 style={{ margin: 0 }}>Geometrie</h3>
        {(f.geometry.type === "polyline" || f.geometry.type === "bezier") && (
          <button
            className={`btn small${selectedPoint === MOVE_ALL ? " active" : ""}`}
            title="Den ganzen Strip in der 3D-Ansicht an den Pfeilen verschieben"
            onClick={() => select(f.id, selectedPoint === MOVE_ALL ? null : MOVE_ALL)}
          >
            Ganzen Strip verschieben
          </button>
        )}
      </div>
      <GeometryEditor f={f} onChange={(g) => set((x) => (x.geometry = g))} />
      <div className="row between" style={{ marginTop: 12 }}>
        <button
          className="btn small"
          onClick={() => {
            const copy: Fixture = structuredClone(f);
            copy.id = Math.random().toString(16).slice(2, 14);
            copy.name = `${f.name} Kopie`;
            update((p) => ({ ...p, fixtures: [...p.fixtures, copy] }));
            select(copy.id);
          }}
        >
          Duplizieren
        </button>
        <button
          className="btn danger small"
          onClick={() => {
            update((p) => ({
              ...p,
              fixtures: p.fixtures.filter((x) => x.id !== f.id),
              controllers: p.controllers.map((c) => ({ ...c, mappings: c.mappings.filter((m) => m.fixture_id !== f.id) })),
            }));
            select(null);
          }}
        >
          <Icon name="trash" /> Löschen
        </button>
      </div>
      {project.controllers.length > 0 && !project.controllers.some((c) => c.mappings.some((m) => m.fixture_id === f.id)) && (
        <p className="hint">Noch keinem Controller zugeordnet (Tab „Controller").</p>
      )}
    </div>
  );
}

export function FixturesView() {
  const project = useStore((s) => s.project);
  const leds = useStore((s) => s.leds);
  const selected = useStore((s) => s.selectedFixture);
  const select = useStore((s) => s.selectFixture);
  const update = useStore((s) => s.updateProject);
  const error = useStore((s) => s.projectError);
  const [wall, setWall] = useState(0);
  if (!project) return null;
  const fixture = project.fixtures.find((f) => f.id === selected);
  const total = leds?.count ?? 0;

  const add = (id: PresetId) => {
    const f = makePreset(id, project.room, wall);
    update((p) => ({ ...p, fixtures: [...p.fixtures, f] }));
    select(f.id);
  };

  return (
    <div className="view split">
      <div className="pane">
        <div className="row between">
          <h2>LED-Strips</h2>
          <span className="badge info">{total} LEDs gesamt</span>
        </div>
        {error && <div className="banner err">{error}</div>}
        <h3>Hinzufügen</h3>
        <Field label="an Wand">
          <select value={wall} onChange={(e) => setWall(+e.target.value)}>
            {project.room.floor.map((_, i) => (
              <option key={i} value={i}>
                Wand {i + 1} ({wallLength(project.room, i).toFixed(2)} m)
              </option>
            ))}
          </select>
        </Field>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, marginBottom: 8 }}>
          {PRESETS.map((p) => (
            <button key={p.id} className="btn small" title={p.hint} onClick={() => add(p.id)}>
              {p.label}
            </button>
          ))}
        </div>

        <h3>Strips ({project.fixtures.length})</h3>
        <div className="list" style={{ marginBottom: 12 }}>
          {project.fixtures.length === 0 && <p className="hint">Noch keine Strips. Füge oben einen hinzu.</p>}
          {project.fixtures.map((f) => {
            const info = leds?.fixtures.find((x) => x.id === f.id);
            return (
              <div key={f.id} className={`list-item${f.id === selected ? " active" : ""}`} onClick={() => select(f.id)}>
                <span className="swatch" style={{ background: f.id === selected ? "#ffcc33" : "#58627a" }} />
                <div className="grow">
                  <div>{f.name}</div>
                  <div className="meta">
                    {TYPE_LABEL[f.geometry.type]} · {f.led_type.toUpperCase()}
                    {f.tags.length > 0 && ` · ${f.tags.join(", ")}`}
                  </div>
                </div>
                <span className="meta">{info ? `${info.count} LEDs` : "…"}</span>
              </div>
            );
          })}
        </div>

        {fixture && <FixtureEditor f={fixture} project={project} />}
      </div>
      <div className="pane flush">
        <div className="canvas-wrap">
          <Scene3D editable />
        </div>
        <div className="overlay">
          <span className="badge">Strip anklicken, dann einen Punkt oder die Raute in der Mitte (ganzer Strip) an den Pfeilen ziehen</span>
        </div>
      </div>
    </div>
  );
}
