import { useEffect, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import type { Version } from "../types";

const SOURCE: Record<string, { label: string; cls: string }> = {
  ui: { label: "Du", cls: "" },
  ai: { label: "KI", cls: "info" },
  system: { label: "System", cls: "" },
  restore: { label: "Wiederhergestellt", cls: "warn" },
};

export function relativeTime(t: number): string {
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 60) return "gerade eben";
  if (s < 3600) return `vor ${Math.floor(s / 60)} min`;
  if (s < 86400) return `vor ${Math.floor(s / 3600)} h`;
  return new Date(t * 1000).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
}

/** Version list of a show or of the project, with restore. */
export function Versions({ showId, limit = 40 }: { showId?: string; limit?: number }) {
  const slug = useStore((s) => s.slug)!;
  const rev = useStore((s) => s.showRevision);
  const project = useStore((s) => s.project);
  const notify = useStore((s) => s.notify);
  const [versions, setVersions] = useState<Version[] | null>(null);
  const projectDep = showId ? null : project; // project edits add project versions

  useEffect(() => {
    (showId ? api.showVersions(slug, showId) : api.projectVersions(slug)).then(setVersions).catch(() => setVersions([]));
  }, [slug, showId, rev, projectDep]);

  if (!versions) return <p className="hint">Lade Verlauf…</p>;
  if (versions.length === 0) return <p className="hint">Noch keine Versionen.</p>;
  return (
    <div className="list">
      {versions.slice(0, limit).map((v, i) => {
        const src = SOURCE[v.source] ?? SOURCE.ui;
        return (
          <div key={v.id} className="list-item" style={{ cursor: "default", alignItems: "flex-start" }}>
            <div className="grow">
              <div className="row" style={{ gap: 6 }}>
                <span className={`badge ${src.cls}`}>{src.label}</span>
                <span className="unit">{relativeTime(v.time)}</span>
                {i === 0 && <span className="badge ok">aktuell</span>}
              </div>
              <div style={{ marginTop: 4, fontSize: 13 }}>{v.summary}</div>
            </div>
            {i > 0 && (
              <button
                className="btn small"
                onClick={async () => {
                  if (!confirm("Diese Version wiederherstellen? Der aktuelle Stand bleibt im Verlauf erhalten.")) return;
                  if (showId) await api.restoreShowVersion(slug, showId, v.id);
                  else await api.restoreProjectVersion(slug, v.id);
                  notify("Version wiederhergestellt", "success");
                  setVersions(await (showId ? api.showVersions(slug, showId) : api.projectVersions(slug)));
                }}
              >
                Wiederherstellen
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
