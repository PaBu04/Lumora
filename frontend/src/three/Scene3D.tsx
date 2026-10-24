import { GizmoHelper, GizmoViewport, Line, OrbitControls, OrthographicCamera, PerspectiveCamera, TransformControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { bounds, geometryCenter, geometryPath, handles, round, setHandle, snapPoint, translateGeometry } from "../geometry";
import { useStore } from "../store";
import type { Fixture, LedData, Project, Room, Vec3, Viewer } from "../types";
import { liveFrame } from "../ws";

// the backend uses z-up coordinates; make three.js agree
THREE.Object3D.DEFAULT_UP.set(0, 0, 1);

const LED_RADIUS = 0.02;
const IDLE = new THREE.Color("#4a5468");

function RoomModel({ room }: { room: Room }) {
  const floor = useMemo(() => {
    const shape = new THREE.Shape(room.floor.map(([x, y]) => new THREE.Vector2(x, y)));
    return new THREE.ShapeGeometry(shape);
  }, [room]);
  const edges = useMemo(() => {
    const segs: Vec3[][] = [];
    const n = room.floor.length;
    for (let i = 0; i < n; i++) {
      const [ax, ay] = room.floor[i];
      const [bx, by] = room.floor[(i + 1) % n];
      segs.push([[ax, ay, 0], [bx, by, 0]], [[ax, ay, room.height], [bx, by, room.height]], [[ax, ay, 0], [ax, ay, room.height]]);
    }
    return segs;
  }, [room]);
  const grid = useMemo(() => {
    const b = bounds(room);
    const segs: Vec3[][] = [];
    for (let x = Math.ceil(b.x0); x <= b.x1; x++) segs.push([[x, b.y0, 0.001], [x, b.y1, 0.001]]);
    for (let y = Math.ceil(b.y0); y <= b.y1; y++) segs.push([[b.x0, y, 0.001], [b.x1, y, 0.001]]);
    return segs;
  }, [room]);
  const walls = useMemo(
    () =>
      room.floor.map((a, i) => {
        const b = room.floor[(i + 1) % room.floor.length];
        const geo = new THREE.BufferGeometry();
        const h = room.height;
        geo.setAttribute(
          "position",
          new THREE.Float32BufferAttribute([a[0], a[1], 0, b[0], b[1], 0, b[0], b[1], h, a[0], a[1], 0, b[0], b[1], h, a[0], a[1], h], 3),
        );
        return geo;
      }),
    [room],
  );
  return (
    <group>
      <mesh geometry={floor}>
        <meshBasicMaterial color="#10141b" side={THREE.DoubleSide} />
      </mesh>
      {walls.map((g, i) => (
        <mesh key={i} geometry={g}>
          <meshBasicMaterial color="#1a2030" transparent opacity={0.18} side={THREE.DoubleSide} depthWrite={false} />
        </mesh>
      ))}
      {grid.map((s, i) => (
        <Line key={`g${i}`} points={s} color="#1d2430" lineWidth={1} />
      ))}
      {edges.map((s, i) => (
        <Line key={`e${i}`} points={s} color="#465063" lineWidth={1} />
      ))}
    </group>
  );
}

function LedInstances({ leds, highlight }: { leds: LedData; highlight: { start: number; count: number } | null }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const seen = useRef("");
  const color = useMemo(() => new THREE.Color(), []);

  useEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    const m = new THREE.Matrix4();
    for (let i = 0; i < leds.count; i++) {
      m.makeTranslation(leds.positions[i * 3], leds.positions[i * 3 + 1], leds.positions[i * 3 + 2]);
      mesh.setMatrixAt(i, m);
      mesh.setColorAt(i, IDLE);
    }
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    seen.current = "";
  }, [leds]);

  useFrame(() => {
    const mesh = ref.current;
    if (!mesh) return;
    const hasFrame = liveFrame.count === leds.count && liveFrame.version > 0;
    const key = `${hasFrame ? liveFrame.version : -1}|${highlight?.start}|${highlight?.count}|${leds.count}`;
    if (key === seen.current) return;
    seen.current = key;
    const c = liveFrame.colors;
    for (let i = 0; i < leds.count; i++) {
      const r = hasFrame ? c[i * 3] / 255 : 0,
        g = hasFrame ? c[i * 3 + 1] / 255 : 0,
        b = hasFrame ? c[i * 3 + 2] / 255 : 0;
      if (highlight && i >= highlight.start && i < highlight.start + highlight.count) {
        // first LED (data input) green, rest of the selected strip amber
        color.set(i === highlight.start ? "#33ff66" : "#ffb020").multiplyScalar(r + g + b > 0.02 ? 1 : 0.8);
      } else if (r + g + b < 0.02) color.copy(IDLE);
      else color.setRGB(r * 2.2, g * 2.2, b * 2.2, THREE.SRGBColorSpace);
      mesh.setColorAt(i, color);
    }
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  });

  return (
    <instancedMesh key={leds.count} ref={ref} args={[undefined, undefined, Math.max(leds.count, 1)]} frustumCulled={false}>
      <sphereGeometry args={[LED_RADIUS, 8, 6]} />
      <meshBasicMaterial toneMapped={false} />
    </instancedMesh>
  );
}

function FixturePaths({ project, editable }: { project: Project; editable: boolean }) {
  const selected = useStore((s) => s.selectedFixture);
  const select = useStore((s) => s.selectFixture);
  return (
    <group>
      {project.fixtures.map((f) => {
        const pts = geometryPath(f.geometry);
        const isSel = f.id === selected;
        if (pts.length < 2) return null;
        return (
          <Line
            key={f.id}
            points={pts}
            color={isSel ? "#ffcc33" : editable ? "#58627a" : "#2c3341"}
            lineWidth={isSel ? 3 : 1.5}
            onClick={
              editable
                ? (e) => {
                    e.stopPropagation();
                    select(f.id);
                  }
                : undefined
            }
          />
        );
      })}
    </group>
  );
}

function Handle({ p, active, onSelect, onMove }: { p: Vec3; active: boolean; onSelect: () => void; onMove: (p: Vec3) => void }) {
  const mesh = useRef<THREE.Mesh>(null!);
  return (
    <>
      <mesh
        ref={mesh}
        position={p}
        onClick={(e) => {
          e.stopPropagation();
          onSelect();
        }}
      >
        <sphereGeometry args={[0.05, 16, 12]} />
        <meshBasicMaterial color={active ? "#ffcc33" : "#c8d0e0"} />
      </mesh>
      {active && (
        <TransformControls
          object={mesh}
          mode="translate"
          size={0.7}
          onMouseUp={() => {
            const v = mesh.current.position;
            onMove([v.x, v.y, v.z]);
          }}
        />
      )}
    </>
  );
}

/** Grip in the middle of a strip: drag it to move the whole strip. */
function MoveAllHandle({ fixture, active, onSelect }: { fixture: Fixture; active: boolean; onSelect: () => void }) {
  const update = useStore((s) => s.updateProject);
  const group = useRef<THREE.Group>(null!);
  const center = geometryCenter(fixture.geometry);
  const rel = geometryPath(fixture.geometry).map((p) => [p[0] - center[0], p[1] - center[1], p[2] - center[2]] as Vec3);
  return (
    <>
      <group ref={group} position={center}>
        <mesh
          onClick={(e) => {
            e.stopPropagation();
            onSelect();
          }}
        >
          <octahedronGeometry args={[0.08]} />
          <meshBasicMaterial color={active ? "#ffcc33" : "#7dd3fc"} />
        </mesh>
        {active && rel.length > 1 && <Line points={rel} color="#ffcc33" lineWidth={2} transparent opacity={0.6} />}
      </group>
      {active && (
        <TransformControls
          object={group}
          mode="translate"
          size={0.8}
          onMouseUp={() => {
            const v = group.current.position;
            const d: Vec3 = [round(v.x - center[0], 2), round(v.y - center[1], 2), round(v.z - center[2], 2)];
            if (d.some((x) => x !== 0))
              update((pr) => {
                const f = pr.fixtures.find((x) => x.id === fixture.id)!;
                f.geometry = translateGeometry(f.geometry, d);
                return pr;
              });
          }}
        />
      )}
    </>
  );
}

export const MOVE_ALL = -1; // selectedPoint value: the whole strip is selected for moving

function FixtureHandles({ project }: { project: Project }) {
  const selected = useStore((s) => s.selectedFixture);
  const point = useStore((s) => s.selectedPoint);
  const select = useStore((s) => s.selectFixture);
  const update = useStore((s) => s.updateProject);
  const fixture = project.fixtures.find((f) => f.id === selected);
  if (!fixture) return null;
  const many = handles(fixture.geometry).length > 1;
  return (
    <group>
      {many && (
        <MoveAllHandle
          key={`${fixture.id}-all-${JSON.stringify(fixture.geometry)}`}
          fixture={fixture}
          active={point === MOVE_ALL}
          onSelect={() => select(fixture.id, MOVE_ALL)}
        />
      )}
      {handles(fixture.geometry).map((p, i) => (
        <Handle
          key={`${fixture.id}-${i}-${p.join(",")}`}
          p={p}
          active={point === i}
          onSelect={() => select(fixture.id, i)}
          onMove={(np) =>
            update((pr) => {
              const f = pr.fixtures.find((x) => x.id === fixture.id)!;
              f.geometry = setHandle(f.geometry, i, snapPoint(np, pr.room));
              return pr;
            })
          }
        />
      ))}
    </group>
  );
}

function viewerForward(v: Viewer): THREE.Vector3 {
  const yaw = (v.yaw_deg * Math.PI) / 180,
    pitch = (v.pitch_deg * Math.PI) / 180;
  return new THREE.Vector3(Math.cos(yaw) * Math.cos(pitch), Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch));
}

const BODY = "#8b96ad";
const BODY_ACTIVE = "#ffcc33";

/** A simple person: head, shoulders and legs, turned to the viewing direction; two short
 * yellow lines from the eyes show where the viewer looks. */
function ViewerMarker({ viewer, editable }: { viewer: Viewer; editable: boolean }) {
  const selected = useStore((s) => s.selectedFixture);
  const select = useStore((s) => s.selectFixture);
  const update = useStore((s) => s.updateProject);
  const group = useRef<THREE.Group>(null!);
  const fwd = viewerForward(viewer);
  const [x, y, z] = viewer.position;
  const active = editable && selected === "__viewer__";
  const color = active ? BODY_ACTIVE : BODY;
  const yaw = (viewer.yaw_deg * Math.PI) / 180;
  const side = new THREE.Vector3(-Math.sin(yaw), Math.cos(yaw), 0); // left of the viewing direction
  const eye = (s: number): Vec3 => [side.x * s * 0.045 + fwd.x * 0.09, side.y * s * 0.045 + fwd.y * 0.09, 0.02];
  const sight = (s: number): [Vec3, Vec3] => {
    const a = eye(s);
    return [a, [a[0] + fwd.x * 0.06, a[1] + fwd.y * 0.06, a[2] + fwd.z * 0.06]];
  };
  const leg = z - 0.72; // from the hips to the floor
  return (
    <group key={viewer.position.join(",")}>
      <group
        ref={group}
        position={viewer.position}
        onClick={(e) => {
          if (!editable) return;
          e.stopPropagation();
          select("__viewer__");
        }}
      >
        {/* head */}
        <mesh position={[0, 0, 0.03]}>
          <sphereGeometry args={[0.1, 24, 18]} />
          <meshLambertMaterial color={color} />
        </mesh>
        <group rotation={[0, 0, yaw]}>
          {/* torso: a slightly flattened capsule, shoulders across the view */}
          <mesh position={[0, 0, -0.42]} rotation={[Math.PI / 2, 0, 0]} scale={[0.62, 1, 1]}>
            <capsuleGeometry args={[0.17, 0.32, 6, 16]} />
            <meshLambertMaterial color={color} />
          </mesh>
          {/* legs */}
          {leg > 0.25 &&
            [-1, 1].map((s) => (
              <mesh key={s} position={[0, s * 0.075, -0.72 - leg / 2]} rotation={[Math.PI / 2, 0, 0]}>
                <capsuleGeometry args={[0.055, leg - 0.11, 4, 10]} />
                <meshLambertMaterial color={color} />
              </mesh>
            ))}
        </group>
        <Line points={sight(1)} color="#ffcc33" lineWidth={2.5} />
        <Line points={sight(-1)} color="#ffcc33" lineWidth={2.5} />
      </group>
      {/* footprint on the floor */}
      <mesh position={[x, y, 0.004]}>
        <ringGeometry args={[0.16, 0.2, 32]} />
        <meshBasicMaterial color={active ? BODY_ACTIVE : "#465063"} side={THREE.DoubleSide} />
      </mesh>
      {active && (
        <TransformControls
          object={group}
          mode="translate"
          size={0.7}
          onMouseUp={() => {
            const v = group.current.position;
            update((pr) => {
              const p = snapPoint([v.x, v.y, v.z], pr.room, 0.05, 0);
              pr.viewer.position = [p[0], p[1], Math.max(0.3, p[2])];
              return pr;
            });
          }}
        />
      )}
    </group>
  );
}

function ViewerCamera({ viewer }: { viewer: Viewer }) {
  const cam = useRef<THREE.PerspectiveCamera>(null!);
  const { size } = useThree();
  useEffect(() => {
    const fwd = viewerForward(viewer);
    const [x, y, z] = viewer.position;
    cam.current.position.set(x, y, z);
    cam.current.up.set(0, 0, 1);
    cam.current.lookAt(x + fwd.x, y + fwd.y, z + fwd.z);
  }, [viewer, size]);
  return <PerspectiveCamera ref={cam} makeDefault fov={75} near={0.05} far={100} />;
}

// last orbit view, so switching between perspective and orthographic keeps the angle
const lastView: { pos: Vec3 | null; target: Vec3 | null } = { pos: null, target: null };

function loadOrtho(): boolean {
  try {
    return localStorage.getItem("lumora.ortho") === "1";
  } catch {
    return false;
  }
}

function OrbitCamera({ ortho, home, target, span }: { ortho: boolean; home: Vec3; target: Vec3; span: number }) {
  const { size } = useThree();
  const pos = lastView.pos ?? home;
  // narrow, tall areas would cut off the sides: widen the view so it shows as much as a square one
  const aspect = size.width / Math.max(1, size.height);
  const fov = aspect >= 1 ? 45 : (2 * Math.atan(Math.tan((22.5 * Math.PI) / 180) / Math.max(0.2, aspect)) * 180) / Math.PI;
  const tgt = lastView.target ?? target;
  // fit the room once when switching to orthographic; the user zooms from there
  const zoom = useMemo(() => Math.min(size.width, size.height) / (span * 1.7), [ortho]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      {ortho ? (
        <OrthographicCamera makeDefault position={pos} zoom={zoom} near={-200} far={400} />
      ) : (
        <PerspectiveCamera makeDefault position={pos} fov={fov} near={0.05} far={200} />
      )}
      <OrbitControls
        key={ortho ? "o" : "p"}
        makeDefault
        target={tgt}
        onChange={(e) => {
          const c = e?.target;
          if (!c) return;
          lastView.pos = [c.object.position.x, c.object.position.y, c.object.position.z];
          lastView.target = [c.target.x, c.target.y, c.target.z];
        }}
      />
    </>
  );
}

export function Scene3D({
  editable = false,
  editViewer = false,
  viewerCam = false,
  highlight = null,
}: {
  editable?: boolean;
  editViewer?: boolean;
  viewerCam?: boolean;
  /** strip to mark without editing it (e.g. the mapping row under the mouse) */
  highlight?: string | null;
}) {
  const project = useStore((s) => s.project);
  const leds = useStore((s) => s.leds);
  const select = useStore((s) => s.selectFixture);
  const selected = useStore((s) => s.selectedFixture);
  const [ortho, setOrtho] = useState(loadOrtho);
  if (!project) return null;
  const b = bounds(project.room);
  const marked = highlight ?? (editable ? selected : null);
  const hl = leds && marked ? (leds.fixtures.find((f) => f.id === marked) ?? null) : null;
  const cx = (b.x0 + b.x1) / 2,
    cy = (b.y0 + b.y1) / 2;
  const span = Math.max(b.x1 - b.x0, b.y1 - b.y0, project.room.height);
  const home: Vec3 = [cx - span * 0.9, cy - span * 1.2, project.room.height + span * 0.9];
  const toggle = (o: boolean) => {
    setOrtho(o);
    try {
      localStorage.setItem("lumora.ortho", o ? "1" : "0");
    } catch {
      /* private mode */
    }
  };
  return (
    <div className="scene3d">
      <Canvas dpr={[1, 2]} gl={{ antialias: true, preserveDrawingBuffer: true }} onPointerMissed={() => (editable || editViewer) && select(null)}>
        <color attach="background" args={["#07090d"]} />
        <hemisphereLight args={["#ffffff", "#2a3040", 1.6]} />
        <directionalLight position={[2, -3, 5]} intensity={1.2} />
        <RoomModel room={project.room} />
        {leds && <LedInstances leds={leds} highlight={hl} />}
        <FixturePaths project={project} editable={editable} />
        {editable && <FixtureHandles project={project} />}
        {!viewerCam && <ViewerMarker viewer={project.viewer} editable={editViewer} />}
        {viewerCam ? <ViewerCamera viewer={project.viewer} /> : <OrbitCamera ortho={ortho} home={home} target={[cx, cy, project.room.height / 3]} span={span} />}
        <EffectComposer>
          <Bloom mipmapBlur intensity={1.1} luminanceThreshold={0.25} luminanceSmoothing={0.3} />
        </EffectComposer>
        {!viewerCam && (
          <GizmoHelper alignment="bottom-left" margin={[64, 64]} renderPriority={2}>
            <GizmoViewport axisColors={["#ef5f6b", "#5fd38d", "#5b9cff"]} labelColor="#0b0d12" axisHeadScale={0.9} />
          </GizmoHelper>
        )}
      </Canvas>
      {!viewerCam && (
        <div className="scene-tools">
          <div className="seg" role="group" aria-label="Kamera">
            <button className={!ortho ? "on" : ""} title="Perspektivische Ansicht" onClick={() => toggle(false)}>
              Perspektive
            </button>
            <button className={ortho ? "on" : ""} title="Orthografische Ansicht ohne Verzerrung (gut zum Ausrichten)" onClick={() => toggle(true)}>
              Orthografisch
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
