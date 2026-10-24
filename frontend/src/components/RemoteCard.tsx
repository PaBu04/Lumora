import { useEffect, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import { useStore } from "../store";

type Info = { enabled: boolean; running: boolean; error: string | null; url: string | null; qr: string | null };

/** Phone remote: switch on, scan the QR code with a phone in the same Wi-Fi. */
export function RemoteCard() {
  const notify = useStore((s) => s.notify);
  const [info, setInfo] = useState<Info | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.remote().then(setInfo);
  }, []);
  if (!info) return null;
  const set = async (body: { enabled?: boolean; new_key?: boolean }) => {
    setBusy(true);
    try {
      setInfo(await api.setRemote(body));
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="card">
      <div className="row between">
        <strong>{t("Handy als Fernbedienung")}</strong>
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={info.enabled} disabled={busy} onChange={(e) => void set({ enabled: e.target.checked })} />
          {t("an")}
        </label>
      </div>
      {!info.enabled ? (
        <p className="hint" style={{ margin: "6px 0 0" }}>
          {t("Abspielen, Helligkeit, Show wechseln und Cues vom Handy aus – im selben WLAN, geschützt durch einen Code im QR-Code.")}
        </p>
      ) : (
        <>
          {info.error && <div className="banner err">{info.error}</div>}
          {info.qr && <div className="remote-qr" dangerouslySetInnerHTML={{ __html: info.qr }} />}
          <p className="hint" style={{ margin: "6px 0" }}>
            {t("Mit der Handy-Kamera scannen. Fragt Windows nach der Firewall, „Private Netzwerke“ erlauben.")}
          </p>
          {info.url && <code className="remote-url">{info.url}</code>}
          <button className="btn ghost small" disabled={busy} onClick={() => void set({ new_key: true })} style={{ marginTop: 6 }}>
            {t("Neuen Code erzeugen (alter Link gilt nicht mehr)")}
          </button>
        </>
      )}
    </div>
  );
}
