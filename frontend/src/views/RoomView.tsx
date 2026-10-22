import { Panes } from "../components/Panes";
import { useMemo, useRef, useState } from "react";
import { api } from "../api";
import { bounds, geometryPath, polygonArea, round, wallLength } from "../geometry";
import { useStore } from "../store";
import { Versions } from "../components/Versions";
import { Scene3D } from "../three/Scene3D";
import type { Project, Room, Vec2 } from "../types";
import { Field, NumberInput, TextInput, Vec3Input } from "../ui";

function segmentsIntersect(a: Vec2, b: Vec2, c: Vec2, d: Vec2): boolean {
  const o = (p: Vec2, q: Vec2, r: Vec2) => (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
  const o1 = o(a, b, c),
    o2 = o(a, b, d),
    o3 = o(c, d, a),
    o4 = o(c, d, b);
  return o1 * o2 < 0 && o3 * o4 < 0;
}

export function isSimplePolygon(pts: Vec2[]): boolean {
  const n = pts.length;
  if (n < 3 || Math.abs(polygonArea(pts)) < 1e-4) return false;
  for (let i = 0; i < n; i++)
    for (let j = i + 2; j < n; j++) {
      if (i === 0 && j === n - 1) continue;
      if (segmentsIntersect(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n])) return false;
    }
  return true;
}

const SHAPES: Record<string, (w: number, d: number) => Vec2[]> = {
  Rechteck: (w, d) => [[0, 0], [w, 0], [w, d], [0, d]],
  "L-Form": (w, d) => [[0, 0], [w, 0], [w, d * 0.55], [w * 0.55, d * 0.55], [w * 0.55, d], [0, d]],
  "U-Form": (w, d) => [[0, 0], [w, 0], [w, d], [w * 0.65, d], [w * 0.65, d * 0.45], [w * 0.35, d * 0.45], [w * 0.35, d], [0, d]],
  Achteck: (w, d) => {
    const c = Math.min(w, d) * 0.25;
    return [[c, 0], [w - c, 0], [w, c], [w, d - c], [w - c, d], [c, d], [0, d - c], [0, c]];
  },
};

type PlanMode = "edit" | "scale" | "trace";

function FloorPlanEditor({
  room,
  onChange,
  mode,
  marks,
  onPlanClick,
  imageUrl,
}: {
  room: Room;
  onChange: (floor: Vec2[]) => void;
  mode: PlanMode;
  marks: Vec2[];
  onPlanClick: (p: Vec2) => void;
  imageUrl: string | null;
}) {
  const project = useStore((s) => s.project)!;
  const fp = project.floorplan;
  const notify = useStore((s) => s.notify);
  const svg = useRef<SVGSVGElement>(null);
  const update = useStore((s) => s.updateProject);
  const [drag, setDrag] = useState<{ i: number; pts: Vec2[] } | null>(null);
  const [viewerDrag, setViewerDrag] = useState<Vec2 | null>(null);
  const pts = drag?.pts ?? room.floor;

  // view box from the committed room so the view does not jump while dragging
  const fpBox = fp ? { x0: fp.x, y0: fp.y, x1: fp.x + fp.width_m, y1: fp.y + (fp.width_m * fp.px_height) / fp.px_width } : null;
  const vb = useMemo(() => {
    const r = bounds(room);
    const b = fpBox
      ? { x0: Math.min(r.x0, fpBox.x0), y0: Math.min(r.y0, fpBox.y0), x1: Math.max(r.x1, fpBox.x1), y1: Math.max(r.y1, fpBox.y1) }
      : r;
    const m = Math.max(1, Math.max(b.x1 - b.x0, b.y1 - b.y0) * 0.18);
    return { x: b.x0 - m, y: -(b.y1 + m), w: b.x1 - b.x0 + 2 * m, h: b.y1 - b.y0 + 2 * m };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [room, fpBox?.x0, fpBox?.y0, fpBox?.x1, fpBox?.y1]);
  const unit = Math.max(vb.w, vb.h) / 60; // ~ one "pixel-ish" size for strokes and labels

  const toWorld = (e: React.PointerEvent): Vec2 => {
    const ctm = svg.current!.getScreenCTM()!.inverse();
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm);
    const g = e.shiftKey ? 0.01 : 0.05;
    return [round(Math.round(p.x / g) * g), round(Math.round(-p.y / g) * g)];
  };

  const commit = (next: Vec2[]) => {
    if (!isSimplePolygon(next)) {
      notify("Ungültiger Grundriss: Wände dürfen sich nicht kreuzen", "error");
      return;
    }
    onChange(next);
  };

  const grid: React.ReactNode[] = [];
  for (let x = Math.ceil(vb.x * 2) / 2; x <= vb.x + vb.w; x += 0.5)
    grid.push(<line key={`x${x}`} x1={x} x2={x} y1={vb.y} y2={vb.y + vb.h} stroke={Number.isInteger(x) ? "#232a37" : "#161b24"} strokeWidth={unit * 0.08} />);
  for (let y = Math.ceil(vb.y * 2) / 2; y <= vb.y + vb.h; y += 0.5)
    grid.push(<line key={`y${y}`} y1={y} y2={y} x1={vb.x} x2={vb.x + vb.w} stroke={Number.isInteger(y) ? "#232a37" : "#161b24"} strokeWidth={unit * 0.08} />);

  const n = pts.length;
  const ccw = polygonArea(pts) > 0;
  const editing = mode === "edit";
  const yaw = (project.viewer.yaw_deg * Math.PI) / 180;
  const [vx, vy] = viewerDrag ?? project.viewer.position;
  const fx = Math.cos(yaw),
    fy = Math.sin(yaw);
  const eyes = [-1, 1].map((s) => {
    const ex = vx - fy * s * unit * 0.28 + fx * unit * 0.3,
      ey = vy + fx * s * unit * 0.28 + fy * unit * 0.3;
    return <line key={s} x1={ex} y1={-ey} x2={ex + fx * unit * 1.1} y2={-(ey + fy * unit * 1.1)} stroke="#ffcc33" strokeWidth={unit * 0.16} strokeLinecap="round" />;
  });
  const endViewerDrag = () => {
    if (!viewerDrag) return;
    const [x, y] = viewerDrag;
    update((p) => ({ ...p, viewer: { ...p.viewer, position: [x, y, p.viewer.position[2]] } }));
    setViewerDrag(null);
  };

  return (
    <svg
      ref={svg}
      className="floorplan"
      viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
      style={{ cursor: mode === "edit" ? undefined : "crosshair" }}
      onPointerDown={(e) => {
        if (mode === "edit") return;
        const ctm = svg.current!.getScreenCTM()!.inverse();
        const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm);
        onPlanClick([round(p.x), round(-p.y)]);
      }}
      onPointerMove={(e) => {
        if (viewerDrag) setViewerDrag(toWorld(e));
        if (!drag) return;
        const next = drag.pts.slice();
        next[drag.i] = toWorld(e);
        setDrag({ ...drag, pts: next });
      }}
      onPointerUp={() => {
        if (drag) commit(drag.pts);
        setDrag(null);
        endViewerDrag();
      }}
      onPointerLeave={() => {
        if (drag) commit(drag.pts);
        setDrag(null);
        endViewerDrag();
      }}
    >
      {grid}
      {fp && fpBox && imageUrl && (
        <image
          href={imageUrl}
          x={fpBox.x0}
          y={-fpBox.y1}
          width={fpBox.x1 - fpBox.x0}
          height={fpBox.y1 - fpBox.y0}
          opacity={fp.opacity}
          preserveAspectRatio="none"
          style={{ pointerEvents: "none" }}
        />
      )}
      <polygon
        points={pts.map(([x, y]) => `${x},${-y}`).join(" ")}
        fill="#121722"
        fillOpacity={fp ? 0.35 : 1}
        stroke="#7a86a0"
        strokeWidth={unit * 0.15}
        strokeLinejoin="round"
        style={{ pointerEvents: "none" }}
      />
      {project.fixtures.map((f) => {
        const path = geometryPath(f.geometry);
        return (
          <polyline
            key={f.id}
            points={path.map(([x, y]) => `${x},${-y}`).join(" ")}
            fill="none"
            stroke="#ff2d95"
            strokeOpacity={0.7}
            strokeWidth={unit * 0.18}
          />
        );
      })}
      <g
        className="viewer-2d"
        style={editing ? undefined : { pointerEvents: "none" }}
        onPointerDown={(e) => {
          e.stopPropagation();
          (e.target as Element).setPointerCapture?.(e.pointerId);
          setViewerDrag([vx, vy]);
        }}
      >
        <ellipse cx={vx} cy={-vy} rx={unit * 0.75} ry={unit * 0.75} fill="#8b96ad" fillOpacity={0.35} />
        <circle cx={vx} cy={-vy} r={unit * 0.5} fill="#e8ecf4" />
        {eyes}
        <title>Betrachter (ziehen zum Verschieben)</title>
      </g>
      {pts.map((a, i) => {
        const b = pts[(i + 1) % n];
        const mx = (a[0] + b[0]) / 2,
          my = (a[1] + b[1]) / 2;
        const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
        // outward normal for the label
        const s = ccw ? 1 : -1;
        const nx = ((b[1] - a[1]) / len) * s,
          ny = (-(b[0] - a[0]) / len) * s;
        return (
          <g key={`w${i}`}>
            <text
              x={mx + nx * unit * (1.2 + 1.6 * Math.abs(nx))}
              y={-(my + ny * unit * 1.3)}
              fontSize={unit * 0.85}
              fill="#a3abbd"
              textAnchor="middle"
              dominantBaseline="middle"
            >
              {len.toFixed(2)} m
            </text>
            <circle
              style={editing ? undefined : { display: "none" }}
              className="insert"
              cx={mx}
              cy={-my}
              r={unit * 0.35}
              fill="#00d4ff"
              onPointerDown={(e) => {
                e.stopPropagation();
                const next = pts.slice();
                next.splice(i + 1, 0, [round(mx), round(my)]);
                commit(next);
              }}
            >
              <title>Ecke einfügen</title>
            </circle>
          </g>
        );
      })}
      {pts.map(([x, y], i) => (
        <circle
          key={`v${i}`}
          className="vertex"
          style={editing ? undefined : { pointerEvents: "none", opacity: 0.4 }}
          cx={x}
          cy={-y}
          r={unit * 0.5}
          fill={drag?.i === i ? "#ff2d95" : "#e6e9f0"}
          onPointerDown={(e) => {
            e.stopPropagation();
            (e.target as Element).setPointerCapture?.(e.pointerId);
            setDrag({ i, pts: room.floor.slice() });
          }}
          onDoubleClick={() => {
            if (n <= 3) return;
            commit(pts.filter((_, j) => j !== i));
          }}
        >
          <title>{`Ecke ${i + 1}: ${x.toFixed(2)} / ${y.toFixed(2)} m (Doppelklick: löschen)`}</title>
        </circle>
      ))}
      {marks.length > 0 && (
        <g style={{ pointerEvents: "none" }}>
          <polyline
            points={marks.map(([x, y]) => `${x},${-y}`).join(" ")}
            fill="none"
            stroke={mode === "scale" ? "#ffcc33" : "#00d4ff"}
            strokeWidth={unit * 0.2}
            strokeDasharray={mode === "scale" ? `${unit * 0.6} ${unit * 0.4}` : undefined}
          />
          {marks.map(([x, y], i) => (
            <circle key={i} cx={x} cy={-y} r={unit * 0.4} fill={mode === "scale" ? "#ffcc33" : "#00d4ff"} />
          ))}
        </g>
      )}
    </svg>
  );
}

function ViewerEditor({ project }: { project: Project }) {
  const update = useStore((s) => s.updateProject);
  const select = useStore((s) => s.selectFixture);
  const selected = useStore((s) => s.selectedFixture);
  const v = project.viewer;
  const active = selected === "__viewer__";
  return (
    <>
      <div className="row between" style={{ margin: "18px 0 8px" }}>
        <h3 style={{ margin: 0 }}>Betrachter</h3>
        <button className={`btn small${active ? " active" : ""}`} onClick={() => select(active ? null : "__viewer__")}>
          In 3D verschieben
        </button>
      </div>
      <p className="hint">Wo du sitzt oder stehst und wohin du schaust. Effekte wie „von links nach rechts“ richten sich danach.</p>
      <Field label="Position (m)">
        <Vec3Input value={v.position} onChange={(position) => update((p) => ({ ...p, viewer: { ...p.viewer, position } }))} />
      </Field>
      <Field label="Blickrichtung">
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input
            type="range"
            className="grow"
            min={0}
            max={359}
            value={Math.round(v.yaw_deg)}
            onChange={(e) => update((p) => ({ ...p, viewer: { ...p.viewer, yaw_deg: +e.target.value } }))}
          />
          <div style={{ width: 72, flex: "none" }}>
            <NumberInput value={v.yaw_deg} step={5} onChange={(yaw_deg) => update((p) => ({ ...p, viewer: { ...p.viewer, yaw_deg: ((yaw_deg % 360) + 360) % 360 } }))} />
          </div>
          <span className="unit">°</span>
        </div>
      </Field>
      <Field label="Neigung">
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <div className="grow">
            <NumberInput value={v.pitch_deg} step={5} min={-89} max={89} onChange={(pitch_deg) => update((p) => ({ ...p, viewer: { ...p.viewer, pitch_deg } }))} />
          </div>
          <span className="unit">°</span>
        </div>
      </Field>
    </>
  );
}

export function RoomView() {
  const project = useStore((s) => s.project);
  const slug = useStore((s) => s.slug);
  const update = useStore((s) => s.updateProject);
  const notify = useStore((s) => s.notify);
  const refreshProjects = useStore((s) => s.refreshProjects);
  const [shape, setShape] = useState("Rechteck");
  const [mode, setMode] = useState<PlanMode>("edit");
  const [marks, setMarks] = useState<Vec2[]>([]);
  const [imgVersion, setImgVersion] = useState(0);
  const setProject = useStore.setState;
  const [w, setW] = useState(5);
  const [d, setD] = useState(4);
  if (!project || !slug) return null;
  const room = project.room;
  const area = Math.abs(polygonArea(room.floor));
  const perimeter = room.floor.reduce((s, _, i) => s + wallLength(room, i), 0);

  const setFloor = (floor: Vec2[]) =>
    update((p) => {
      p.room.floor = floor;
      return p;
    });

  return (
    <Panes id="room" sizes={[400, null]} className="view">
      <div className="pane">
        <h2>Raum</h2>
        <Field label="Projektname">
          <TextInput
            value={project.name}
            onChange={(name) => {
              update((p) => ({ ...p, name }));
              setTimeout(refreshProjects, 600);
            }}
          />
        </Field>
        <Field label="Raumhöhe">
          <div className="row">
            <div className="grow">
              <NumberInput value={room.height} step={0.05} min={1} max={20} onChange={(height) => update((p) => ({ ...p, room: { ...p.room, height } }))} />
            </div>
            <span className="unit">m</span>
          </div>
        </Field>
        <p className="hint">Im Grundriss Ecken ziehen. Punkte auf den Wänden fügen eine Ecke ein, Doppelklick löscht eine. Mit Shift feiner.</p>
        <div className="row" style={{ marginBottom: 12 }}>
          <span className="badge">{area.toFixed(1)} m²</span>
          <span className="badge">Umfang {perimeter.toFixed(1)} m</span>
          <span className="badge">{room.floor.length} Wände</span>
        </div>

        <h3>Plan oder Foto nachzeichnen</h3>
        <div className="card">
          {!project.floorplan ? (
            <>
              <p className="hint" style={{ marginTop: 0 }}>Foto, Bauplan oder Skizze hochladen, Maßstab festlegen und die Ecken nachklicken.</p>
              <label className="btn small">
                Bild auswählen…
                <input
                  type="file"
                  hidden
                  accept="image/png,image/jpeg,image/webp,image/gif,image/bmp"
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    try {
                      const pr = await api.uploadFloorplan(slug, file);
                      setProject({ project: pr });
                      setImgVersion((v) => v + 1);
                      notify("Bild geladen – jetzt den Maßstab festlegen", "success");
                    } catch (err) {
                      notify((err as Error).message, "error");
                    }
                  }}
                />
              </label>
            </>
          ) : (
            <>
              {mode === "scale" && <div className="banner info">Zwei Punkte im Bild anklicken, deren echten Abstand du kennst (z. B. eine Wand).</div>}
              {mode === "trace" && (
                <div className="banner info">
                  Ecken des Raums der Reihe nach anklicken ({marks.length} gesetzt).
                  <div className="row" style={{ marginTop: 6 }}>
                    <button
                      className="btn primary small"
                      disabled={marks.length < 3}
                      onClick={() => {
                        if (!isSimplePolygon(marks)) return notify("Die Linien kreuzen sich – bitte Ecken in Reihenfolge setzen", "error");
                        setFloor(marks);
                        setMarks([]);
                        setMode("edit");
                        notify("Grundriss übernommen", "success");
                      }}
                    >
                      Als Grundriss übernehmen
                    </button>
                    <button className="btn small" disabled={!marks.length} onClick={() => setMarks((m) => m.slice(0, -1))}>
                      Letzte Ecke entfernen
                    </button>
                  </div>
                </div>
              )}
              <div className="row" style={{ marginBottom: 8 }}>
                <button className={`btn small${mode === "scale" ? " active" : ""}`} onClick={() => { setMarks([]); setMode(mode === "scale" ? "edit" : "scale"); }}>
                  Maßstab festlegen
                </button>
                <button className={`btn small${mode === "trace" ? " active" : ""}`} onClick={() => { setMarks([]); setMode(mode === "trace" ? "edit" : "trace"); }}>
                  Nachzeichnen
                </button>
                <button
                  className="btn ghost small danger"
                  onClick={async () => {
                    setProject({ project: await api.deleteFloorplan(slug) });
                    setMode("edit");
                    setMarks([]);
                  }}
                >
                  Bild entfernen
                </button>
              </div>
              <Field label="Deckkraft">
                <input type="range" min={0.05} max={1} step={0.05} value={project.floorplan.opacity} onChange={(e) => update((p) => ({ ...p, floorplan: { ...p.floorplan!, opacity: +e.target.value } }))} />
              </Field>
              <Field label="Breite (m)">
                <NumberInput value={project.floorplan.width_m} min={0.2} step={0.1} onChange={(v) => update((p) => ({ ...p, floorplan: { ...p.floorplan!, width_m: v } }))} />
              </Field>
              <Field label="Position x / y (m)">
                <div className="row" style={{ flexWrap: "nowrap" }}>
                  <NumberInput value={project.floorplan.x} step={0.05} onChange={(v) => update((p) => ({ ...p, floorplan: { ...p.floorplan!, x: v } }))} />
                  <NumberInput value={project.floorplan.y} step={0.05} onChange={(v) => update((p) => ({ ...p, floorplan: { ...p.floorplan!, y: v } }))} />
                </div>
              </Field>
            </>
          )}
        </div>

        <h3>Vorlage</h3>
        <div className="card">
          <Field label="Form">
            <select value={shape} onChange={(e) => setShape(e.target.value)}>
              {Object.keys(SHAPES).map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </Field>
          <Field label="Breite × Tiefe">
            <div className="row">
              <div className="grow">
                <NumberInput value={w} min={1} max={100} step={0.1} onChange={setW} />
              </div>
              <span className="unit">×</span>
              <div className="grow">
                <NumberInput value={d} min={1} max={100} step={0.1} onChange={setD} />
              </div>
              <span className="unit">m</span>
            </div>
          </Field>
          <div className="row end">
            <button
              className="btn"
              onClick={() => {
                setFloor(SHAPES[shape](w, d).map(([x, y]) => [round(x), round(y)] as Vec2));
                notify(`Grundriss „${shape}" übernommen`, "success");
              }}
            >
              Übernehmen
            </button>
          </div>
        </div>

        <h3>Ecken</h3>
        <table className="grid">
          <thead>
            <tr>
              <th>#</th>
              <th>x (m)</th>
              <th>y (m)</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {room.floor.map((pt, i) => (
              <tr key={i}>
                <td className="unit">{i + 1}</td>
                {[0, 1].map((k) => (
                  <td key={k}>
                    <NumberInput
                      value={pt[k]}
                      step={0.05}
                      onChange={(v) => {
                        const next = room.floor.map((q) => [...q] as Vec2);
                        next[i][k] = v;
                        if (isSimplePolygon(next)) setFloor(next);
                        else notify("Ungültiger Grundriss: Wände dürfen sich nicht kreuzen", "error");
                      }}
                    />
                  </td>
                ))}
                <td>
                  <button className="btn ghost small" disabled={room.floor.length <= 3} onClick={() => setFloor(room.floor.filter((_, j) => j !== i))}>
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <ViewerEditor project={project} />

        <h3>Verlauf</h3>
        <p className="hint">Jede gespeicherte Änderung an Raum, Strips, Controllern und Kalibrierung.</p>
        <Versions limit={12} />

        <h3>Projekt</h3>
        <button
          className="btn danger small"
          onClick={async () => {
            if (!confirm(`Projekt „${project.name}" mit allen Shows löschen?`)) return;
            await api.deleteProject(slug);
            location.reload();
          }}
        >
          Projekt löschen
        </button>
      </div>
      <Panes id="room-right" dir="col" sizes={[null, 380]}>
        <div style={{ position: "relative", minHeight: 0, overflow: "hidden" }}>
          <FloorPlanEditor
            room={room}
            onChange={setFloor}
            mode={mode}
            marks={marks}
            imageUrl={project.floorplan ? `/api/projects/${slug}/floorplan?v=${imgVersion}-${project.floorplan.filename}` : null}
            onPlanClick={(p) => {
              if (mode === "trace") setMarks((m) => [...m, p]);
              if (mode === "scale") {
                const next = [...marks, p].slice(-2);
                setMarks(next);
                if (next.length === 2 && project.floorplan) {
                  const d = Math.hypot(next[1][0] - next[0][0], next[1][1] - next[0][1]);
                  const real = parseFloat((prompt(`Wie lang ist diese Strecke in Wirklichkeit (m)? Aktuell ${d.toFixed(2)} m`, d.toFixed(2)) ?? "").replace(",", "."));
                  if (Number.isFinite(real) && real > 0 && d > 0) {
                    const k = real / d;
                    update((pr) => {
                      const f = pr.floorplan!;
                      // scale around the first point so it stays where it is
                      pr.floorplan = { ...f, width_m: round(f.width_m * k), x: round(next[0][0] - (next[0][0] - f.x) * k), y: round(next[0][1] - (next[0][1] - f.y) * k) };
                      return pr;
                    });
                    notify(`Maßstab gesetzt (×${k.toFixed(3)})`, "success");
                  }
                  setMarks([]);
                  setMode("edit");
                }
              }
            }}
          />
          <div className="overlay">
            <span className="badge">Grundriss (Draufsicht)</span>
          </div>
        </div>
        <div style={{ position: "relative" }}>
          <div className="canvas-wrap">
            <Scene3D editViewer />
          </div>
          <div className="overlay">
            <span className="badge">3D-Ansicht</span>
          </div>
        </div>
      </Panes>
    </Panes>
  );
}
