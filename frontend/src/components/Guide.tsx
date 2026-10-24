import { useEffect, useState } from "react";
import { t } from "../i18n";
import { useStore, type Tab } from "../store";
import { Help } from "./Help";

interface Step {
  id: string;
  tab: Tab;
  title: string;
  text: string;
  done: boolean;
  skip?: string;
}

/** "First steps": a checklist in the sidebar that follows what is already set up. */
export function Guide() {
  const show = useStore((s) => s.guide);
  const setGuide = useStore((s) => s.setGuide);
  const tab = useStore((s) => s.tab);
  const setTab = useStore((s) => s.setTab);
  const project = useStore((s) => s.project);
  const songs = useStore((s) => s.songs);
  const shows = useStore((s) => s.shows);
  const playing = useStore((s) => !!s.playback?.playing);
  const marks = useStore((s) => s.guideMarks);
  const mark = useStore((s) => s.markGuide);
  const [open, setOpen] = useState(true);

  useEffect(() => {
    if (tab === "room" && !marks.room) mark("room");
  }, [tab, marks.room, mark]);
  useEffect(() => {
    if (playing && !marks.play) mark("play");
  }, [playing, marks.play, mark]);
  if (!show || !project) return null;

  const steps: Step[] = [
    { id: "room", tab: "room", title: t("Raum zeichnen"), text: t("Grundriss, Höhe und wo du sitzt"), done: !!marks.room },
    {
      id: "strips",
      tab: "fixtures",
      title: t("LED-Strips platzieren"),
      text: t("so wie sie im Raum hängen"),
      done: project.fixtures.length > 0,
    },
    {
      id: "controller",
      tab: "devices",
      title: t("Controller verbinden"),
      text: t("WLED suchen und Strips zuordnen"),
      done: project.controllers.length > 0 || !!marks.controller,
      skip: t("ohne Hardware überspringen"),
    },
    {
      id: "song",
      tab: "songs",
      title: t("Song hochladen"),
      text: t("die Analyse dauert etwa eine Minute"),
      done: songs.some((s) => s.status === "done"),
    },
    { id: "show", tab: "shows", title: t("Show erstellen"), text: t("Starter-Show mit Stil oder mit KI"), done: shows.length > 0 },
    { id: "play", tab: "shows", title: t("Abspielen"), text: t("Leertaste; „Live“ schickt sie an die LEDs"), done: !!marks.play },
  ];
  const done = steps.filter((s) => s.done).length;
  const next = steps.find((s) => !s.done);

  return (
    <div className="guide">
      <div className="guide-head">
        <button className="guide-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
          <strong>{t("Erste Schritte")}</strong>
          <span className="unit">
            {done}/{steps.length}
          </span>
        </button>
        <Help id="firstshow" />
        <button className="btn ghost icon small" title={t("Ausblenden (über „Hilfe“ wieder einblenden)")} onClick={() => setGuide(false)}>
          ✕
        </button>
      </div>
      <div className="guide-bar">
        <div style={{ width: `${(done / steps.length) * 100}%` }} />
      </div>
      {open && (
        <ol className="guide-steps">
          {steps.map((s) => (
            <li key={s.id} className={`${s.done ? "done" : ""}${s === next ? " next" : ""}`}>
              <button className="guide-step" onClick={() => setTab(s.tab)}>
                <span className="guide-check">{s.done ? "✓" : ""}</span>
                <span>
                  <span className="guide-title">{s.title}</span>
                  {s === next && <span className="guide-text">{s.text}</span>}
                </span>
              </button>
              {s === next && s.skip && (
                <button
                  className="btn ghost small guide-skip"
                  onClick={() => mark(s.id)}
                >
                  {s.skip}
                </button>
              )}
            </li>
          ))}
        </ol>
      )}
      {open && !next && (
        <p className="hint" style={{ margin: "6px 2px 0" }}>
          {t("Geschafft! Im Handbuch findest du mehr zu jedem Schritt.")}
        </p>
      )}
    </div>
  );
}
