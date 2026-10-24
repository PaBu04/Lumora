import { useEffect, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import { Modal } from "../ui";

const FRONTEND: { name: string; license: string; use: string }[] = [
  { name: "React, React DOM", license: "MIT", use: "Oberfläche" },
  { name: "three.js", license: "MIT", use: "3D-Ansicht" },
  { name: "@react-three/fiber, drei, postprocessing", license: "MIT", use: "3D-Ansicht" },
  { name: "postprocessing", license: "Zlib", use: "Leuchteffekt der LEDs" },
  { name: "zustand", license: "MIT", use: "Zustand der Oberfläche" },
];

type Lic = { name: string; version?: string; license: string; use: string; bundled?: boolean };

/** About: privacy (what leaves this PC) and the licenses of the components. */
export function About({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<{ python: Lic[]; models: Lic[] } | null>(null);
  useEffect(() => {
    api.licenses().then(setData);
  }, []);
  const table = (rows: Lic[]) => (
    <table className="grid" style={{ marginBottom: 12 }}>
      <tbody>
        {rows.map((r) => (
          <tr key={r.name}>
            <td>
              {r.name}
              {r.version ? <span className="unit"> {r.version}</span> : null}
            </td>
            <td>{r.license}</td>
            <td className="unit">{r.use}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
  return (
    <Modal title={t("Über diese App")} onClose={onClose} width={760}>
      <h3 style={{ marginTop: 0 }}>{t("Datenschutz")}</h3>
      <p>
        {t(
          "Alles läuft lokal auf deinem PC: Songs, Analysen, Räume und Shows bleiben auf diesem Rechner. Die App hat keine Nutzungsstatistik und kein Konto.",
        )}
      </p>
      <p className="hint">{t("Daten verlassen den PC nur in diesen Fällen:")}</p>
      <ul className="hint" style={{ paddingLeft: 18 }}>
        <li>{t("WLED-Controller bekommen die Lichtbilder – nur im eigenen Netzwerk.")}</li>
        <li>{t("Beim ersten Gebrauch lädt die App Modelldaten für die Analyse herunter (Demucs, beat_this).")}</li>
        <li>
          {t(
            "„Mit KI“ startet dein Claude Code: Es schickt deine Beschreibung, Zusammenfassungen der Songanalyse und Bilder der Show an Anthropic und darf kurz im Internet zum Song recherchieren. Ohne diese Funktion geht nichts an Anthropic.",
          )}
        </li>
      </ul>
      <h3>{t("Modelle")}</h3>
      {data ? table(data.models.map((m) => ({ ...m, use: m.use + (m.bundled ? t(" (mitgeliefert)") : t(" (wird bei Bedarf geladen)")) }))) : null}
      <h3>{t("Verwendete Bibliotheken")}</h3>
      {data ? table(data.python) : <p className="hint">{t("Lade…")}</p>}
      {table(FRONTEND)}
      <p className="hint">
        {t(
          "Die vollständigen Lizenztexte liegen den jeweiligen Paketen bei; der Hinweis zu Basic Pitch steht in lsg/audio/models/NOTICE-basic-pitch.",
        )}
      </p>
    </Modal>
  );
}
