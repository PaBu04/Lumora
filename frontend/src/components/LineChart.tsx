import { useEffect, useMemo, useRef, useState } from "react";

export interface Series {
  name: string;
  color: string;
  values: number[];
}

export interface RefLine {
  y: number;
  label: string;
  color: string;
}

/** Small SVG line chart: recessive grid, 2px lines, crosshair tooltip, legend for >= 2 series. */
export function LineChart({
  x,
  series,
  refLines = [],
  height = 180,
  yMax,
  xFormat = (v) => v.toFixed(1),
  yFormat = (v) => v.toFixed(0),
  xLabel,
  yLabel,
  markers = [],
}: {
  x: number[];
  series: Series[];
  refLines?: RefLine[];
  height?: number;
  yMax?: number;
  xFormat?: (v: number) => string;
  yFormat?: (v: number) => string;
  xLabel?: string;
  yLabel?: string;
  markers?: { x: number; y: number }[];
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [width, setWidth] = useState(600);
  const pad = { l: 44, r: series.length > 1 && series.length <= 4 ? 90 : 14, t: 10, b: 30 };

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => el.clientWidth && setWidth(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const { maxY, ticks } = useMemo(() => {
    const dataMax = Math.max(1e-9, ...series.flatMap((s) => s.values), ...refLines.map((r) => r.y));
    const top = yMax ?? dataMax * 1.08;
    const step = niceStep(top / 4);
    const t: number[] = [];
    for (let v = 0; v <= top + 1e-9; v += step) t.push(v);
    return { maxY: Math.max(top, t[t.length - 1]), ticks: t };
  }, [series, refLines, yMax]);

  const x0 = x[0] ?? 0,
    x1 = x[x.length - 1] ?? 1;
  const w = width - pad.l - pad.r,
    h = height - pad.t - pad.b;
  const sx = (v: number) => pad.l + ((v - x0) / Math.max(1e-9, x1 - x0)) * w;
  const sy = (v: number) => pad.t + h - (v / maxY) * h;
  const xTicks = useMemo(() => {
    const step = niceStep((x1 - x0) / 6);
    const t: number[] = [];
    for (let v = Math.ceil(x0 / step) * step; v <= x1 + 1e-9; v += step) t.push(v);
    return t;
  }, [x0, x1]);

  const path = (vals: number[]) => vals.map((v, i) => `${i ? "L" : "M"}${sx(x[i]).toFixed(1)},${sy(v).toFixed(1)}`).join("");

  return (
    <div ref={wrap} style={{ position: "relative", width: "100%" }}>
      {series.length > 1 && (
        <div className="row" style={{ gap: 12, marginBottom: 4 }}>
          {series.map((s) => (
            <span key={s.name} className="row unit" style={{ gap: 6 }}>
              <span style={{ width: 12, height: 2, background: s.color, display: "inline-block", borderRadius: 1 }} />
              {s.name}
            </span>
          ))}
        </div>
      )}
      <svg
        width={width}
        height={height}
        style={{ display: "block" }}
        onPointerMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const px = e.clientX - r.left;
          if (px < pad.l || px > pad.l + w || !x.length) return setHover(null);
          const v = x0 + ((px - pad.l) / w) * (x1 - x0);
          let best = 0;
          for (let i = 1; i < x.length; i++) if (Math.abs(x[i] - v) < Math.abs(x[best] - v)) best = i;
          setHover(best);
        }}
        onPointerLeave={() => setHover(null)}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={pad.l + w} y1={sy(t)} y2={sy(t)} stroke="#1f2532" strokeWidth={1} />
            <text x={pad.l - 6} y={sy(t)} fill="#6d7690" fontSize={10.5} textAnchor="end" dominantBaseline="middle">
              {yFormat(t)}
            </text>
          </g>
        ))}
        {xTicks.map((t) => (
          <text key={t} x={sx(t)} y={pad.t + h + 16} fill="#6d7690" fontSize={10.5} textAnchor="middle">
            {xFormat(t)}
          </text>
        ))}
        <line x1={pad.l} x2={pad.l + w} y1={pad.t + h} y2={pad.t + h} stroke="#343d50" />
        {xLabel && (
          <text x={pad.l + w} y={height - 2} fill="#6d7690" fontSize={10.5} textAnchor="end">
            {xLabel}
          </text>
        )}
        {yLabel && (
          <text x={4} y={pad.t + 2} fill="#6d7690" fontSize={10.5} dominantBaseline="hanging">
            {yLabel}
          </text>
        )}
        {refLines.map((r) => (
          <g key={r.label}>
            <line x1={pad.l} x2={pad.l + w} y1={sy(r.y)} y2={sy(r.y)} stroke={r.color} strokeWidth={1.5} strokeDasharray="5 4" />
            <text x={pad.l + w - 2} y={sy(r.y) - 4} fill="#a3abbd" fontSize={10.5} textAnchor="end">
              {r.label}
            </text>
          </g>
        ))}
        {series.map((s) => (
          <path key={s.name} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {series.length > 1 &&
          series.length <= 4 &&
          series.map((s) => (
            <text key={`l${s.name}`} x={pad.l + w + 6} y={sy(s.values[s.values.length - 1] ?? 0)} fill="#a3abbd" fontSize={10.5} dominantBaseline="middle">
              {s.name.length > 12 ? `${s.name.slice(0, 11)}…` : s.name}
            </text>
          ))}
        {markers.map((m, i) => (
          <circle key={i} cx={sx(m.x)} cy={sy(m.y)} r={4} fill={series[0]?.color ?? "#fff"} stroke="#11151c" strokeWidth={2} />
        ))}
        {hover !== null && (
          <g pointerEvents="none">
            <line x1={sx(x[hover])} x2={sx(x[hover])} y1={pad.t} y2={pad.t + h} stroke="#6d7690" strokeWidth={1} />
            {series.map((s) => (
              <circle key={s.name} cx={sx(x[hover])} cy={sy(s.values[hover] ?? 0)} r={4} fill={s.color} stroke="#11151c" strokeWidth={2} />
            ))}
          </g>
        )}
      </svg>
      {hover !== null && (
        <div
          style={{
            position: "absolute",
            left: Math.min(sx(x[hover]) + 10, width - 170),
            top: series.length > 1 ? 24 : 4,
            background: "var(--bg-4)",
            border: "1px solid var(--line-2)",
            borderRadius: 6,
            padding: "6px 8px",
            fontSize: 12,
            pointerEvents: "none",
            minWidth: 140,
          }}
        >
          <div className="unit">{xFormat(x[hover])}</div>
          {series.map((s) => (
            <div key={s.name} className="row between" style={{ gap: 10 }}>
              <span className="row" style={{ gap: 6 }}>
                <span style={{ width: 8, height: 8, borderRadius: 2, background: s.color }} />
                {series.length > 1 ? s.name : ""}
              </span>
              <strong>{yFormat(s.values[hover] ?? 0)}</strong>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function niceStep(raw: number): number {
  if (raw <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(raw));
  const f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}
