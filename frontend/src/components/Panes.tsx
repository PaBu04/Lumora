import { Children, Fragment, useEffect, useRef, useState, type ReactNode } from "react";

const MIN = 140;

function load(id: string, fallback: (number | null)[]): (number | null)[] {
  try {
    const v = JSON.parse(localStorage.getItem(`lsg.panes.${id}`) ?? "null");
    if (Array.isArray(v) && v.length === fallback.length && v.every((x, i) => (x === null) === (fallback[i] === null))) return v;
  } catch {
    /* no storage */
  }
  return fallback;
}

function save(id: string, v: (number | null)[]) {
  try {
    localStorage.setItem(`lsg.panes.${id}`, JSON.stringify(v));
  } catch {
    /* private mode */
  }
}

/**
 * Areas side by side (dir "row") or stacked ("col") with draggable dividers.
 * `sizes`: pixels per area, null = takes the remaining space. Sizes are remembered per `id`;
 * a double click on a divider restores the default.
 */
export function Panes({
  id,
  sizes,
  dir = "row",
  className = "",
  min = MIN,
  children,
}: {
  id: string;
  sizes: (number | null)[];
  dir?: "row" | "col";
  className?: string;
  min?: number;
  children: ReactNode;
}) {
  const [px, setPx] = useState(() => load(id, sizes));
  const latest = useRef(px);
  latest.current = px;
  const items = Children.toArray(children);
  useEffect(() => setPx(load(id, sizes)), [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const startDrag = (i: number) => (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const gutter = e.currentTarget;
    const container = gutter.parentElement!;
    // the divider between areas i-1 and i resizes the fixed one of the two
    const target = latest.current[i - 1] !== null ? i - 1 : i;
    const sign = target === i - 1 ? 1 : -1;
    const pos = (ev: PointerEvent | React.PointerEvent) => (dir === "row" ? ev.clientX : ev.clientY);
    const start = pos(e);
    const slots = Array.from(container.children).filter((c) => c.classList.contains("pane-slot")) as HTMLElement[];
    const startSize = dir === "row" ? slots[target].offsetWidth : slots[target].offsetHeight;
    const total = dir === "row" ? container.clientWidth : container.clientHeight;
    const others = slots.reduce((s, el, j) => (j === target ? s : s + (latest.current[j] === null ? min : dir === "row" ? el.offsetWidth : el.offsetHeight)), 0);
    const max = Math.max(min, total - others - 6 * (slots.length - 1));
    document.body.classList.add(dir === "row" ? "resizing-col" : "resizing-row");
    const move = (ev: PointerEvent) => {
      const v = Math.round(Math.min(max, Math.max(min, startSize + sign * (pos(ev) - start))));
      setPx((p) => p.map((x, j) => (j === target ? v : x)));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.classList.remove("resizing-col", "resizing-row");
      save(id, latest.current);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div className={`panes dir-${dir} ${className}`}>
      {items.map((child, i) => (
        <Fragment key={i}>
          {i > 0 && (
            <div
              className="gutter"
              role="separator"
              aria-orientation={dir === "row" ? "vertical" : "horizontal"}
              title="Ziehen zum Ändern der Größe · Doppelklick: zurücksetzen"
              onPointerDown={startDrag(i)}
              onDoubleClick={() => {
                setPx(sizes);
                save(id, sizes);
              }}
            />
          )}
          <div className="pane-slot" style={px[i] === null ? { flex: "1 1 0" } : { flex: `0 1 ${px[i]}px` }}>
            {child}
          </div>
        </Fragment>
      ))}
    </div>
  );
}
