import { useEffect, useState } from "react";
import { api } from "../api";
import type { AppSettings } from "../types";
import { Modal } from "../ui";
import { Help } from "./Help";

const LIMITS: { value: number; label: string }[] = [
  { value: 3, label: "höchstens 3 große Blitze pro Sekunde (empfohlen)" },
  { value: 2, label: "höchstens 2 pro Sekunde (vorsichtiger)" },
  { value: 0, label: "keine Begrenzung" },
];

/** Choice of the flash limit (lsg.render.safety). */
export function FlashLimitSelect({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(+e.target.value)}>
      {LIMITS.map((l) => (
        <option key={l.value} value={l.value}>
          {l.label}
        </option>
      ))}
    </select>
  );
}

/** Photosensitivity warning on the first start; confirmed once per installation. */
export function SafetyNotice() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [limit, setLimit] = useState(3);
  useEffect(() => {
    api
      .settings()
      .then((s) => {
        setSettings(s);
        setLimit(s.flash_limit ?? 3);
      })
      .catch(() => setSettings(null));
  }, []);
  if (!settings || settings.safety_ack) return null;
  const confirm = async () => setSettings(await api.saveSettings({ safety_ack: true, flash_limit: limit }));
  return (
    <Modal title="Bevor es losgeht: Lichtempfindlichkeit" onClose={confirm} width={560}>
      <p>
        Lichtshows können schnelle Blitze, Stroboskop-Effekte und starke Hell-Dunkel-Wechsel enthalten. Bei Menschen mit
        lichtempfindlicher Epilepsie können solche Lichtreize Anfälle auslösen, auch ohne bekannte Vorgeschichte.
      </p>
      <ul className="hint" style={{ margin: "0 0 12px", paddingLeft: 18 }}>
        <li>Frag Gäste vor einer Show, ob jemand empfindlich auf Lichtblitze reagiert.</li>
        <li>Brich die Show sofort ab, wenn jemand Schwindel, Sehstörungen oder Zuckungen bemerkt.</li>
        <li>Schau nicht aus kurzer Entfernung direkt in helle LEDs.</li>
      </ul>
      <label className="unit" htmlFor="flash-limit">
        Blitzbegrenzung (gilt für Vorschau, LEDs und Export, später unter „Kalibrierung“ änderbar)
      </label>
      <div id="flash-limit" style={{ margin: "4px 0 14px" }}>
        <FlashLimitSelect value={limit} onChange={setLimit} />
      </div>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn primary" onClick={() => void confirm()}>
          Verstanden
        </button>
      </div>
    </Modal>
  );
}

/** Settings card: flash limit. */
export function SafetyCard() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  useEffect(() => {
    api.settings().then(setSettings);
  }, []);
  if (!settings) return null;
  return (
    <div className="card">
      <strong>
        Sicherheit: Blitzbegrenzung <Help id="flash_limit" />
      </strong>
      <p className="hint">
        Große Blitze über den ganzen Raum werden gedämpft, wenn sie schneller als erlaubt aufeinander folgen; Stroboskope laufen nie
        schneller. Kleine, örtliche Treffer bleiben unverändert. Schützt Menschen mit lichtempfindlicher Epilepsie.
      </p>
      <FlashLimitSelect value={settings.flash_limit} onChange={async (v) => setSettings(await api.saveSettings({ flash_limit: v }))} />
    </div>
  );
}
