import type { Fixture, Geometry, Room, Vec2, Vec3 } from "./types";

export const uid = () => Math.random().toString(16).slice(2, 14);

const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const scale = (a: Vec3, s: number): Vec3 => [a[0] * s, a[1] * s, a[2] * s];
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a: Vec3): Vec3 => {
  const l = Math.hypot(...a) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
};
export const round = (v: number, d = 3) => Math.round(v * 10 ** d) / 10 ** d;

/** Same basis as backend lsg/geometry/sampling._plane_basis. */
function planeBasis(normal: Vec3, reference: Vec3 | null): [Vec3, Vec3] {
  const n = norm(normal);
  let r = reference;
  if (!r) {
    const abs = n.map(Math.abs);
    const i = abs.indexOf(Math.min(...abs));
    r = [0, 0, 0];
    r[i] = 1;
  }
  const u = norm(sub(r, scale(n, dot(r, n))));
  return [u, cross(n, u)];
}

/** Polyline approximating a fixture's geometry (for drawing). */
export function geometryPath(g: Geometry): Vec3[] {
  switch (g.type) {
    case "polyline":
      return g.points;
    case "bezier": {
      const out: Vec3[] = [];
      for (let k = 0; k + 3 < g.points.length; k += 3) {
        const [p0, p1, p2, p3] = g.points.slice(k, k + 4);
        for (let i = k === 0 ? 0 : 1; i <= 24; i++) {
          const t = i / 24;
          const a = (1 - t) ** 3,
            b = 3 * (1 - t) ** 2 * t,
            c = 3 * (1 - t) * t * t,
            d = t ** 3;
          out.push([0, 1, 2].map((j) => a * p0[j] + b * p1[j] + c * p2[j] + d * p3[j]) as Vec3);
        }
      }
      return out;
    }
    case "arc":
    case "circle": {
      const sweep = g.type === "arc" ? g.sweep_deg : 360;
      const [u, v] = planeBasis(g.normal, g.reference);
      const steps = Math.max(8, Math.ceil(Math.abs(sweep) / 5));
      const out: Vec3[] = [];
      for (let i = 0; i <= steps; i++) {
        const a = ((g.start_deg + (sweep * i) / steps) * Math.PI) / 180;
        out.push(add(g.center, add(scale(u, g.radius * Math.cos(a)), scale(v, g.radius * Math.sin(a)))));
      }
      return out;
    }
    case "matrix": {
      const c = scale(norm(g.col_dir), g.pitch * (g.cols - 1));
      const r = scale(norm(g.row_dir), g.pitch * (g.rows - 1));
      const o = g.origin;
      return [o, add(o, c), add(add(o, c), r), add(o, r), o];
    }
  }
}

/** Editable handle points of a geometry and how to write them back. */
export function handles(g: Geometry): Vec3[] {
  switch (g.type) {
    case "polyline":
    case "bezier":
      return g.points;
    case "arc":
    case "circle":
      return [g.center];
    case "matrix":
      return [g.origin];
  }
}

export function setHandle(g: Geometry, i: number, p: Vec3): Geometry {
  switch (g.type) {
    case "polyline":
    case "bezier": {
      const points = g.points.slice();
      points[i] = p;
      return { ...g, points };
    }
    case "arc":
    case "circle":
      return { ...g, center: p };
    case "matrix":
      return { ...g, origin: p };
  }
}

export function polygonArea(pts: Vec2[]): number {
  let a = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x1, y1] = pts[i];
    const [x2, y2] = pts[(i + 1) % pts.length];
    a += x1 * y2 - x2 * y1;
  }
  return a / 2;
}

export function centroid(pts: Vec2[]): Vec2 {
  const n = pts.length;
  return [pts.reduce((s, p) => s + p[0], 0) / n, pts.reduce((s, p) => s + p[1], 0) / n];
}

export function bounds(room: Room) {
  const xs = room.floor.map((p) => p[0]);
  const ys = room.floor.map((p) => p[1]);
  return { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
}

/** Inward offset of a (counter-clockwise) polygon by d metres (mitered corners). */
export function insetPolygon(pts: Vec2[], d: number): Vec2[] {
  const ccw = polygonArea(pts) > 0 ? pts : pts.slice().reverse();
  const n = ccw.length;
  return ccw.map((p, i) => {
    const prev = ccw[(i - 1 + n) % n];
    const next = ccw[(i + 1) % n];
    const e1 = [p[0] - prev[0], p[1] - prev[1]];
    const e2 = [next[0] - p[0], next[1] - p[1]];
    const l1 = Math.hypot(e1[0], e1[1]) || 1;
    const l2 = Math.hypot(e2[0], e2[1]) || 1;
    const n1 = [-e1[1] / l1, e1[0] / l1];
    const n2 = [-e2[1] / l2, e2[0] / l2];
    const k = 1 + n1[0] * n2[0] + n1[1] * n2[1];
    const m = k > 0.1 ? d / k : d;
    return [round(p[0] + (n1[0] + n2[0]) * m), round(p[1] + (n1[1] + n2[1]) * m)] as Vec2;
  });
}

/** Snap a point to a 5 cm grid, onto nearby walls, floor and ceiling. */
export function snapPoint(p: Vec3, room: Room, grid = 0.05, wallSnap = 0.12): Vec3 {
  let [x, y, z] = p.map((v) => Math.round(v / grid) * grid) as Vec3;
  let best = wallSnap;
  const n = room.floor.length;
  for (let i = 0; i < n; i++) {
    const a = room.floor[i];
    const b = room.floor[(i + 1) % n];
    const dx = b[0] - a[0],
      dy = b[1] - a[1];
    const len2 = dx * dx + dy * dy || 1;
    const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2));
    const px = a[0] + t * dx,
      py = a[1] + t * dy;
    const d = Math.hypot(p[0] - px, p[1] - py);
    if (d < best) {
      best = d;
      x = px;
      y = py;
    }
  }
  if (Math.abs(p[2] - room.height) < wallSnap) z = room.height;
  if (Math.abs(p[2]) < wallSnap) z = 0;
  z = Math.max(0, Math.min(room.height, z));
  return [round(x), round(y), round(z)];
}

function baseFixture(name: string, geometry: Geometry, extra: Partial<Fixture> = {}): Fixture {
  return {
    id: uid(),
    name,
    geometry,
    led_type: "ws2812b",
    leds_per_meter: 60,
    led_count: null,
    reverse: false,
    tags: [],
    ...extra,
  };
}

export type PresetId = "ceiling" | "floor" | "wall" | "corner" | "ring" | "matrix" | "polyline" | "bezier" | "arc";

export const PRESETS: { id: PresetId; label: string; hint: string }[] = [
  { id: "ceiling", label: "Deckenumrandung", hint: "Strip rundum knapp unter der Decke" },
  { id: "floor", label: "Bodenleiste", hint: "Strip rundum am Boden" },
  { id: "wall", label: "Wandleiste", hint: "gerader Strip entlang einer Wand" },
  { id: "corner", label: "Eckstreifen", hint: "senkrecht in einer Raumecke" },
  { id: "ring", label: "Deckenring", hint: "Kreis an der Decke" },
  { id: "matrix", label: "LED-Matrix", hint: "16×16 Panel an einer Wand" },
  { id: "polyline", label: "Freie Linie", hint: "Polylinie mit eigenen Punkten" },
  { id: "bezier", label: "Kurve", hint: "Bezier-Kurve" },
  { id: "arc", label: "Bogen", hint: "Kreisbogen" },
];

export function makePreset(id: PresetId, room: Room, wall = 0): Fixture {
  const h = room.height;
  const n = room.floor.length;
  const ccw = polygonArea(room.floor) > 0 ? room.floor : room.floor.slice().reverse();
  const [cx, cy] = centroid(ccw);
  const wa = ccw[wall % n];
  const wb = ccw[(wall + 1) % n];
  const along: Vec3 = norm([wb[0] - wa[0], wb[1] - wa[1], 0]);
  const inward: Vec3 = [-along[1], along[0], 0];
  const onWall = (t: number, z: number, off = 0.01): Vec3 => [
    round(wa[0] + (wb[0] - wa[0]) * t + inward[0] * off),
    round(wa[1] + (wb[1] - wa[1]) * t + inward[1] * off),
    round(z),
  ];
  switch (id) {
    case "ceiling": {
      const pts = insetPolygon(ccw, 0.05).map(([x, y]) => [x, y, round(h - 0.05)] as Vec3);
      return baseFixture("Deckenumrandung", { type: "polyline", points: [...pts, pts[0]] }, { tags: ["ceiling"] });
    }
    case "floor": {
      const pts = insetPolygon(ccw, 0.03).map(([x, y]) => [x, y, 0.05] as Vec3);
      return baseFixture("Bodenleiste", { type: "polyline", points: [...pts, pts[0]] }, { tags: ["floor"] });
    }
    case "wall":
      return baseFixture(`Wandleiste ${wall + 1}`, { type: "polyline", points: [onWall(0.05, 1.2), onWall(0.95, 1.2)] }, { tags: ["wall"] });
    case "corner": {
      const off = 0.05;
      const p: Vec3 = [round(wa[0] + (inward[0] + along[0]) * off), round(wa[1] + (inward[1] + along[1]) * off), 0.1];
      return baseFixture(`Ecke ${wall + 1}`, { type: "polyline", points: [p, [p[0], p[1], round(h - 0.1)]] }, { tags: ["corner"] });
    }
    case "ring":
      return baseFixture(
        "Deckenring",
        { type: "circle", center: [round(cx), round(cy), round(h - 0.02)], radius: 0.6, normal: [0, 0, 1], reference: null, start_deg: 0 },
        { tags: ["ceiling"] },
      );
    case "matrix": {
      const o = onWall(0.5, 1.8, 0.02);
      const pitch = 0.02;
      const shift = scale(along, -pitch * 7.5);
      return baseFixture(
        "Matrix",
        {
          type: "matrix",
          origin: [round(o[0] + shift[0]), round(o[1] + shift[1]), 1.8],
          col_dir: [round(along[0]), round(along[1]), 0],
          row_dir: [0, 0, -1],
          cols: 16,
          rows: 16,
          pitch,
          serpentine: true,
          column_major: false,
        },
        { tags: ["matrix"] },
      );
    }
    case "polyline":
      return baseFixture("Linie", { type: "polyline", points: [onWall(0.2, 1.0, 0.3), onWall(0.5, 1.6, 0.3), onWall(0.8, 1.0, 0.3)] });
    case "bezier": {
      const a = onWall(0.2, 1.0, 0.02),
        d = onWall(0.8, 1.0, 0.02);
      return baseFixture("Kurve", { type: "bezier", points: [a, [a[0], a[1], 2.0], [d[0], d[1], 2.0], d] });
    }
    case "arc":
      return baseFixture("Bogen", {
        type: "arc",
        center: onWall(0.5, 1.0, 0.02),
        radius: 0.8,
        normal: scale(inward, -1), // so that the arc bulges upwards (v = n x u = +z)
        reference: along,
        start_deg: 0,
        sweep_deg: 180,
      });
  }
}

export function wallLength(room: Room, i: number): number {
  const a = room.floor[i];
  const b = room.floor[(i + 1) % room.floor.length];
  return Math.hypot(b[0] - a[0], b[1] - a[1]);
}
