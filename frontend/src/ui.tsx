import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { Vec3 } from "./types";

export function NumberInput({
  value,
  onChange,
  step = 0.01,
  min,
  max,
  disabled,
  title,
  integer = false,
}: {
  value: number;
  onChange: (v: number) => void;
  step?: number;
  min?: number;
  max?: number;
  disabled?: boolean;
  title?: string;
  integer?: boolean;
}) {
  const [text, setText] = useState(String(value));
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    if (!focused) setText(String(value));
  }, [value, focused]);
  const commit = () => {
    let v = parseFloat(text.replace(",", "."));
    if (!Number.isFinite(v)) {
      setText(String(value));
      return;
    }
    if (integer) v = Math.round(v);
    if (min !== undefined) v = Math.max(min, v);
    if (max !== undefined) v = Math.min(max, v);
    setText(String(v));
    if (v !== value) onChange(v);
  };
  return (
    <input
      type="number"
      value={text}
      step={step}
      min={min}
      max={max}
      title={title}
      disabled={disabled}
      onFocus={() => setFocused(true)}
      onBlur={() => {
        setFocused(false);
        commit();
      }}
      onChange={(e) => setText(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
      }}
    />
  );
}

export function TextInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <input
      type="text"
      value={text}
      placeholder={placeholder}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => text !== value && onChange(text)}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
      }}
    />
  );
}

export function Vec3Input({ value, onChange, step = 0.05 }: { value: Vec3; onChange: (v: Vec3) => void; step?: number }) {
  return (
    <div className="vec3">
      {[0, 1, 2].map((i) => (
        <NumberInput
          key={i}
          value={value[i]}
          step={step}
          title={"xyz"[i]}
          onChange={(v) => {
            const next = [...value] as Vec3;
            next[i] = v;
            onChange(next);
          }}
        />
      ))}
    </div>
  );
}

export function Field({ label, children, stack }: { label: ReactNode; children: ReactNode; stack?: boolean }) {
  return (
    <div className={`field${stack ? " stack" : ""}`}>
      <label>{label}</label>
      <div>{children}</div>
    </div>
  );
}

/** Dialog over the app; closes on Escape, the ✕ button or a click next to it. */
export function Modal({ title, onClose, children, width = 760 }: { title: string; onClose: () => void; children: ReactNode; width?: number }) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);
  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ width }} role="dialog" aria-label={title}>
        <div className="modal-head">
          <strong>{title}</strong>
          <button className="btn ghost icon" title="Schließen (Esc)" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}

export interface MenuItem {
  label: string;
  danger?: boolean;
  onClick: () => void;
}

/** Right-click menu: `open(event, items)` shows it at the pointer; render `menu` somewhere. */
export function useContextMenu() {
  const [state, setState] = useState<{ x: number; y: number; items: MenuItem[] } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!state) return;
    const close = (e: Event) => {
      if (e instanceof MouseEvent && ref.current?.contains(e.target as Node)) return;
      setState(null);
    };
    const key = (e: KeyboardEvent) => e.key === "Escape" && setState(null);
    window.addEventListener("mousedown", close);
    window.addEventListener("blur", close);
    window.addEventListener("resize", close);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("blur", close);
      window.removeEventListener("resize", close);
      window.removeEventListener("keydown", key);
    };
  }, [state]);
  const open = (e: React.MouseEvent, items: MenuItem[]) => {
    e.preventDefault();
    e.stopPropagation();
    setState({ x: Math.min(e.clientX, window.innerWidth - 200), y: Math.min(e.clientY, window.innerHeight - 40 * items.length - 12), items });
  };
  const menu = state && (
    <div ref={ref} className="ctx-menu" style={{ left: state.x, top: state.y }} role="menu">
      {state.items.map((it) => (
        <button
          key={it.label}
          role="menuitem"
          className={it.danger ? "danger" : ""}
          onClick={() => {
            setState(null);
            it.onClick();
          }}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
  return { open, menu };
}

export function formatTime(t: number): string {
  if (!Number.isFinite(t)) return "0:00.0";
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}

export function Icon({ name }: { name: string }) {
  const paths: Record<string, ReactNode> = {
    room: <path d="M3 10.5 12 4l9 6.5V20a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z M9 21v-6h6v6" />,
    strip: (
      <>
        <path d="M3 17c4-8 14-8 18 0" />
        <circle cx="6" cy="13" r="1.3" />
        <circle cx="12" cy="10.5" r="1.3" />
        <circle cx="18" cy="13" r="1.3" />
      </>
    ),
    device: (
      <>
        <rect x="4" y="7" width="16" height="10" rx="2" />
        <path d="M8 7V4M16 7V4M8 20v-3M16 20v-3" />
      </>
    ),
    music: (
      <>
        <path d="M9 18V5l11-2v13" />
        <circle cx="6" cy="18" r="3" />
        <circle cx="17" cy="16" r="3" />
      </>
    ),
    show: (
      <>
        <rect x="3" y="5" width="18" height="14" rx="2" />
        <path d="m10 9 5 3-5 3z" />
      </>
    ),
    ai: (
      <>
        <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" />
        <circle cx="12" cy="12" r="3" />
      </>
    ),
    calibrate: (
      <>
        <path d="M4 20h16" />
        <path d="M6 20V14M10 20V10M14 20V7M18 20V4" />
      </>
    ),
    play: <path d="M7 5v14l12-7z" fill="currentColor" />,
    pause: <path d="M7 5h4v14H7zM13 5h4v14h-4z" fill="currentColor" />,
    stop: <rect x="6" y="6" width="12" height="12" rx="1" fill="currentColor" />,
    plus: <path d="M12 5v14M5 12h14" />,
    trash: <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" />,
    info: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 11v6M12 7.5v.5" />
      </>
    ),
    spark: <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z" />,
  };
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" width={18} height={18}>
      {paths[name]}
    </svg>
  );
}
