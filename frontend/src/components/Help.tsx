import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { api } from "../api";
import { About } from "./About";
import { CHAPTERS, HELP, SHORTCUTS } from "../help";
import { lang, setLang, t, tr } from "../i18n";
import { useStore } from "../store";
import { Modal } from "../ui";

/** Help body: paragraphs separated by blank lines, "- " lines become a list. */
export function HelpText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let items: string[] = [];
  const flush = () => {
    if (items.length)
      blocks.push(
        <ul key={blocks.length}>
          {items.map((it, i) => (
            <li key={i}>{it}</li>
          ))}
        </ul>,
      );
    items = [];
  };
  for (const line of text.split("\n")) {
    if (line.startsWith("- ")) items.push(line.slice(2));
    else {
      flush();
      if (line.trim()) blocks.push(<p key={blocks.length}>{line}</p>);
    }
  }
  flush();
  return <div className="help-text">{blocks}</div>;
}

/** (?) next to a term: a short explanation, with a link into the manual. */
export function Help({ id }: { id: string }) {
  const entry = HELP[id];
  const openHelp = useStore((s) => s.openHelp);
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: 0, top: 0 });
  useLayoutEffect(() => {
    if (!open || !btn.current) return;
    const r = btn.current.getBoundingClientRect();
    const w = 340;
    setPos({ left: Math.max(8, Math.min(window.innerWidth - w - 8, r.left - 20)), top: r.bottom + 6 });
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!pop.current?.contains(e.target as Node) && !btn.current?.contains(e.target as Node)) setOpen(false);
    };
    const key = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", key);
    };
  }, [open]);
  if (!entry) return null;
  return (
    <>
      <button
        ref={btn}
        type="button"
        className={`help-btn${open ? " on" : ""}`}
        aria-label={t("Hilfe: {title}", { title: tr(entry.title) })}
        title={tr(entry.title)}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen(!open);
        }}
      >
        ?
      </button>
      {open &&
        createPortal(
          <div ref={pop} className="help-pop" style={{ left: pos.left, top: Math.min(pos.top, window.innerHeight - 120) }} role="dialog">
            <strong>{tr(entry.title)}</strong>
            <HelpText text={tr(entry.body)} />
            <button
              className="btn small ghost"
              onClick={() => {
                setOpen(false);
                openHelp("manual", id);
              }}
            >
              {t("Im Handbuch öffnen")}
            </button>
          </div>,
          document.body,
        )}
    </>
  );
}

/** The manual: every help entry by chapter, searchable. */
export function Manual({ topic, onClose }: { topic?: string; onClose: () => void }) {
  const [current, setCurrent] = useState(topic && HELP[topic] ? topic : "firstshow");
  const [query, setQuery] = useState("");
  const hits = useMemo(() => {
    const q = query.trim().toLowerCase();
    return Object.entries(HELP).filter(([, e]) => !q || `${tr(e.title)} ${tr(e.body)}`.toLowerCase().includes(q));
  }, [query]);
  const entry = HELP[current];
  return (
    <Modal title={t("Handbuch")} onClose={onClose} width={900}>
      <div className="manual">
        <div className="manual-nav">
          <input type="search" placeholder={t("Suchen…")} value={query} onChange={(e) => setQuery(e.target.value)} autoFocus />
          {Object.entries(CHAPTERS).map(([ch, title]) => {
            const items = hits.filter(([, e]) => e.chapter === ch);
            if (!items.length) return null;
            return (
              <div key={ch}>
                <div className="manual-chapter">{tr(title)}</div>
                {items.map(([id, e]) => (
                  <button key={id} className={`manual-item${id === current ? " active" : ""}`} onClick={() => setCurrent(id)}>
                    {tr(e.title)}
                  </button>
                ))}
              </div>
            );
          })}
          {!hits.length && <p className="hint">{t("Nichts gefunden.")}</p>}
        </div>
        <div className="manual-body">
          {entry && (
            <>
              <div className="unit">{tr(CHAPTERS[entry.chapter])}</div>
              <h2 style={{ marginTop: 2 }}>{tr(entry.title)}</h2>
              <HelpText text={tr(entry.body)} />
            </>
          )}
        </div>
      </div>
    </Modal>
  );
}

export function Shortcuts({ onClose }: { onClose: () => void }) {
  return (
    <Modal title={t("Tastenkürzel")} onClose={onClose} width={560}>
      <table className="grid">
        <tbody>
          {SHORTCUTS.map((s) => (
            <tr key={s.keys}>
              <td style={{ whiteSpace: "nowrap" }}>
                <span className="kbd">{s.keys}</span>
              </td>
              <td>{tr(s)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Modal>
  );
}

/** Diagnostics for bug reports: shows what is in it before it is saved. */
function Diagnostics({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<{ diagnostics: Record<string, unknown>; log: string } | null>(null);
  useEffect(() => {
    api.diagnostics().then(setData);
  }, []);
  return (
    <Modal title={t("Diagnosepaket")} onClose={onClose} width={820}>
      <p className="hint" style={{ marginTop: 0 }}>
        {t(
          "Hilft bei Fehlerberichten: Versionen, Einstellungen, Anzahlen (Strips, LEDs, Controller mit Firmware) und die letzten Log-Zeilen. Namen von Projekten, Strips, Songs und Controllern, IP- und MAC-Adressen, Rechnernamen, Benutzerpfade und E-Mail-Adressen sind entfernt. So sieht der Inhalt aus:",
        )}
      </p>
      {!data ? (
        <p className="hint">{t("Sammle…")}</p>
      ) : (
        <>
          <pre className="code diag-pre">{JSON.stringify(data.diagnostics, null, 2)}</pre>
          <strong className="unit">log.txt</strong>
          <pre className="code diag-pre" style={{ maxHeight: 140 }}>
            {data.log.split("\n").slice(-60).join("\n")}
          </pre>
        </>
      )}
      <div className="row" style={{ justifyContent: "flex-end", marginTop: 10 }}>
        <a className="btn primary" href="/api/diagnostics?download=true" download>
          {t("Als Datei speichern")}
        </a>
      </div>
    </Modal>
  );
}

/** Help windows, opened from anywhere through the store; "?" opens the shortcuts. */
export function HelpWindows() {
  const help = useStore((s) => s.help);
  const openHelp = useStore((s) => s.openHelp);
  const closeHelp = useStore((s) => s.closeHelp);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "?" && !(e.target as HTMLElement).closest("input, textarea, select")) {
        e.preventDefault();
        openHelp("shortcuts");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openHelp]);
  if (!help) return null;
  if (help.kind === "diagnostics") return <Diagnostics onClose={closeHelp} />;
  if (help.kind === "about") return <About onClose={closeHelp} />;
  return help.kind === "manual" ? <Manual topic={help.topic} onClose={closeHelp} /> : <Shortcuts onClose={closeHelp} />;
}

/** Top bar: help menu (manual, shortcuts, first steps, language). */
export function HelpMenu() {
  const openHelp = useStore((s) => s.openHelp);
  const setGuide = useStore((s) => s.setGuide);
  const expert = useStore((s) => s.expert);
  const setExpert = useStore((s) => s.setExpert);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);
  const item = (label: string, fn: () => void) => (
    <button
      className="menu-item"
      onClick={() => {
        setOpen(false);
        fn();
      }}
    >
      {label}
    </button>
  );
  return (
    <div className="help-menu" ref={ref}>
      <button className="btn ghost small" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        ? {t("Hilfe")}
      </button>
      {open && (
        <div className="menu" role="menu" style={{ right: 0, top: "calc(100% + 4px)" }}>
          {item(t("Handbuch"), () => openHelp("manual"))}
          {item(t("Erste Schritte anzeigen"), () => setGuide(true))}
          {item(t("Tastenkürzel  (?)"), () => openHelp("shortcuts"))}
          {item(t("Diagnosepaket für Fehlerberichte…"), () => openHelp("diagnostics"))}
          {item(t("Über diese App, Datenschutz, Lizenzen"), () => openHelp("about"))}
          <div className="menu-sep" />
          {item(expert ? t("Expertenmodus ausschalten") : t("Expertenmodus einschalten"), () => setExpert(!expert))}
          {item(lang === "de" ? "English" : "Deutsch", () => setLang(lang === "de" ? "en" : "de"))}
        </div>
      )}
    </div>
  );
}
