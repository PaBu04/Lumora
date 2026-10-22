import { useMemo, useState } from "react";
import { api } from "../api";
import { levelForPwm, pwmOf, SERIES } from "../calibration";
import { LineChart } from "../components/LineChart";
import { useStore } from "../store";
import type { LedCalibration, LedType } from "../types";
import { Field, NumberInput } from "../ui";

const TYPE_LABEL: Record<LedType, string> = { ws2812b: "WS2812B", sk6812: "SK6812 (RGB)", sk6812_rgbw: "SK6812 RGBW" };
const RAW_STEPS = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 24, 32];
const pct = (v: number) => `${Math.round(v * 100)} %`;

function CurveCharts({ cal }: { cal: LedCalibration }) {
  const full = useMemo(() => {
    const x = Array.from({ length: 101 }, (_, i) => i / 100);
    return { x, y: x.map((v) => pwmOf(v, cal)) };
  }, [cal]);
  const dark = useMemo(() => {
    const x = Array.from({ length: 121 }, (_, i) => (i / 120) * 0.3);
    return { x, y: x.map((v) => pwmOf(v, cal)) };
  }, [cal]);
  const ramp = [1, 2, 3, 4, 5, 6, 7, 8].map((i) => i / 8);
  return (
    <>
      <div className="card">
        <strong>PWM-Wert je wahrgenommener Helligkeit</strong>
        <p className="hint">Shows rechnen mit wahrgenommener Helligkeit; diese Kurve setzt sie in den Wert um, den die LED bekommt.</p>
        <LineChart
          x={full.x}
          series={[{ name: "PWM", color: SERIES[0], values: full.y }]}
          yMax={256}
          height={200}
          xFormat={pct}
          yFormat={(v) => v.toFixed(0)}
          xLabel="wahrgenommen"
          yLabel="PWM"
          markers={ramp.map((v) => ({ x: v, y: pwmOf(v, cal) }))}
        />
      </div>
      <div className="card">
        <strong>Dunkler Bereich 0–30 %</strong>
        <p className="hint">
          Hier entscheidet sich, ob dunkle Szenen funktionieren. Jede ganze PWM-Stufe ist eine sichtbare Stufe – Bereiche, in denen die Kurve
          weniger als 1 steigt, sehen ohne Dithering gleich aus.
        </p>
        <LineChart
          x={dark.x}
          series={[{ name: "PWM", color: SERIES[0], values: dark.y }]}
          height={170}
          xFormat={pct}
          yFormat={(v) => v.toFixed(0)}
          xLabel="wahrgenommen"
          yLabel="PWM"
          refLines={[{ y: cal.min_level, label: `Mindeststufe ${cal.min_level}`, color: "#a3abbd" }]}
        />
        <table className="grid" style={{ marginTop: 8 }}>
          <thead>
            <tr>
              <th>wahrgenommen</th>
              {[0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1].map((v) => (
                <th key={v}>{pct(v)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="unit">PWM</td>
              {[0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1].map((v) => (
                <td key={v}>{pwmOf(v, cal).toFixed(1)}</td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </>
  );
}

function Step({ n, title, children, pattern, onShow, active }: { n: number; title: string; children: React.ReactNode; pattern: string; onShow: (kind: string) => void; active: boolean }) {
  return (
    <div className={`card${active ? " selected" : ""}`}>
      <div className="row between" style={{ marginBottom: 6 }}>
        <strong>
          {n}. {title}
        </strong>
        <button className={`btn small${active ? " active" : ""}`} onClick={() => onShow(pattern)}>
          {active ? "Muster läuft" : "Muster zeigen"}
        </button>
      </div>
      {children}
    </div>
  );
}

export function CalibrationView() {
  const project = useStore((s) => s.project);
  const update = useStore((s) => s.updateProject);
  const pb = useStore((s) => s.playback);
  const setPlayback = useStore((s) => s.setPlayback);
  const notify = useStore((s) => s.notify);
  const usedTypes = useMemo(() => {
    const t = [...new Set(project?.fixtures.map((f) => f.led_type) ?? [])];
    return t.length ? t : (["ws2812b"] as LedType[]);
  }, [project]);
  const [type, setType] = useState<LedType>(usedTypes[0]);
  const [fixture, setFixture] = useState<string>("");
  const [whiteLevel, setWhiteLevel] = useState(0.7);
  if (!project) return null;
  const ledType = usedTypes.includes(type) ? type : usedTypes[0];
  const cal = project.calibration[ledType];
  const fixtures = project.fixtures.filter((f) => f.led_type === ledType);
  const target = fixtures.find((f) => f.id === fixture)?.id ?? fixtures[0]?.id ?? null;
  const set = (patch: Partial<LedCalibration>) =>
    update((p) => {
      p.calibration[ledType] = { ...p.calibration[ledType], ...patch };
      return p;
    });
  const testing = pb?.test;
  const show = async (kind: string, params: Record<string, unknown> = {}) => {
    if (!target) return notify("Kein Strip dieses Typs vorhanden", "error");
    setPlayback(await api.test(true, target, kind, params));
  };
  const live = pb?.mode === "live";
  const darkFloor = levelForPwm(cal.min_level + 1, cal);

  return (
    <div className="view split-right" style={{ gridTemplateColumns: "1fr minmax(360px, 420px)" }}>
      <div className="pane">
        <div className="row between">
          <h2>Kalibrierung</h2>
          <div className="row">
            {usedTypes.map((t) => (
              <button key={t} className={`btn small${t === ledType ? " active" : ""}`} onClick={() => setType(t)}>
                {TYPE_LABEL[t]}
              </button>
            ))}
          </div>
        </div>
        <p className="hint">
          LEDs werden nicht gleichmäßig heller: Die Stufen 1 → 2 → 3 sind große Sprünge, 254 → 255 sieht man nicht. Die App rechnet deshalb in
          wahrgenommener Helligkeit und setzt sie hier in PWM-Werte um. Kalibriere einmal pro LED-Typ – am besten im abgedunkelten Raum.
        </p>
        <CurveCharts cal={cal} />
      </div>

      <div className="pane">
        <div className="card">
          <div className="row between" style={{ marginBottom: 8 }}>
            <strong>Assistent</strong>
            <div className="row">
              {!live && (
                <button className="btn small" onClick={async () => setPlayback(await api.mode("live"))} title="Muster auch an die echten LEDs senden">
                  An LEDs senden
                </button>
              )}
              {testing && (
                <button className="btn small active" onClick={async () => setPlayback(await api.test(false, null))}>
                  Muster beenden
                </button>
              )}
            </div>
          </div>
          {!live && <p className="hint">Muster erscheinen in der 3D-Vorschau; für die Kalibrierung „An LEDs senden" aktivieren.</p>}
          <Field label="Test-Strip">
            <select value={target ?? ""} onChange={(e) => setFixture(e.target.value)}>
              {fixtures.length === 0 && <option value="">(kein Strip dieses Typs)</option>}
              {fixtures.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <Step n={1} title="Mindeststufe finden" pattern="steps" onShow={(k) => show(k)} active={testing?.kind === "steps"}>
          <p className="hint">
            Der Strip zeigt Segmente mit den Roh-Werten 1, 2, 3, 4, 5, 6, 8 … 255. Welches ist das erste Segment, das klar und farbtreu leuchtet?
          </p>
          <div className="row">
            {RAW_STEPS.map((v) => (
              <button key={v} className={`btn small${cal.min_level === v ? " active" : ""}`} onClick={() => set({ min_level: v })}>
                {v}
              </button>
            ))}
          </div>
        </Step>

        <Step n={2} title="Gleichmäßige Stufen" pattern="ramp" onShow={(k) => show(k)} active={testing?.kind === "ramp"}>
          <p className="hint">8 Segmente mit 12,5 % … 100 % wahrgenommener Helligkeit sollten gleichmäßig ansteigen. Wirken die hellen Segmente zu ähnlich, Gamma erhöhen; wirken die dunklen zu ähnlich, senken.</p>
          <Field label="Kurve">
            <select value={cal.curve} onChange={(e) => set({ curve: e.target.value as LedCalibration["curve"] })}>
              <option value="cie">CIE L* (empfohlen)</option>
              <option value="gamma">Gamma</option>
            </select>
          </Field>
          {cal.curve === "gamma" && (
            <Field label={`Gamma ${cal.gamma.toFixed(2)}`}>
              <input type="range" min={1} max={3.5} step={0.05} value={cal.gamma} onChange={(e) => set({ gamma: +e.target.value })} />
            </Field>
          )}
          <Field label="Maximum (PWM)">
            <NumberInput integer value={cal.max_level} min={16} max={255} step={1} onChange={(v) => set({ max_level: v })} />
          </Field>
        </Step>

        <Step n={3} title="Dunkle Szenen" pattern="dark" onShow={(k) => show(k)} active={testing?.kind === "dark"}>
          <p className="hint">
            Segmente mit 1 %, 2 %, 3 %, 5 %, 7 %, 10 %, 15 %, 20 %. Unter ca. {pct(darkFloor)} liegen die Stufen weniger als einen PWM-Schritt
            auseinander – Dithering verteilt Zwischenwerte räumlich bzw. zeitlich.
          </p>
          <Field label="Aus unterhalb">
            <div className="row">
              <input type="range" className="grow" min={0} max={0.05} step={0.001} value={cal.cutoff} onChange={(e) => set({ cutoff: +e.target.value })} />
              <span className="unit" style={{ width: 44 }}>
                {(cal.cutoff * 100).toFixed(1)} %
              </span>
            </div>
          </Field>
          <Field label="Dithering">
            <select value={cal.dithering} onChange={(e) => set({ dithering: e.target.value as LedCalibration["dithering"] })}>
              <option value="none">aus</option>
              <option value="spatial">räumlich (benachbarte LEDs)</option>
              <option value="temporal">zeitlich (kann bei 50 FPS leicht flimmern)</option>
            </select>
          </Field>
        </Step>

        <Step n={4} title="Weißabgleich" pattern="white" onShow={(k) => show(k, { level: whiteLevel })} active={testing?.kind === "white"}>
          <p className="hint">Weiß sollte neutral wirken (z. B. neben einem weißen Blatt Papier). Den zu starken Kanal reduzieren.</p>
          <Field label={`Helligkeit ${pct(whiteLevel)}`}>
            <input
              type="range"
              min={0.05}
              max={1}
              step={0.05}
              value={whiteLevel}
              onChange={(e) => {
                setWhiteLevel(+e.target.value);
                if (testing?.kind === "white") void show("white", { level: +e.target.value });
              }}
            />
          </Field>
          {(["Rot", "Grün", "Blau"] as const).map((label, i) => (
            <Field key={label} label={`${label} ${Math.round(cal.white_balance[i] * 100)} %`}>
              <input
                type="range"
                min={0.5}
                max={1}
                step={0.01}
                value={cal.white_balance[i]}
                onChange={(e) => {
                  const wb = [...cal.white_balance] as [number, number, number];
                  wb[i] = +e.target.value;
                  set({ white_balance: wb });
                }}
              />
            </Field>
          ))}
          {ledType === "sk6812_rgbw" && (
            <>
              <Field label="Weiß-LED nutzen">
                <select value={cal.white_mode} onChange={(e) => set({ white_mode: e.target.value as LedCalibration["white_mode"] })}>
                  <option value="color">farbrichtig (empfohlen)</option>
                  <option value="min">einfach (Minimum)</option>
                  <option value="off">nicht nutzen</option>
                </select>
              </Field>
              {cal.white_mode === "color" && (
                <Field label="Farbe der Weiß-LED">
                  <div className="row">
                    <input type="color" value={cal.white_color} onChange={(e) => set({ white_color: e.target.value })} />
                    <span className="unit">warmweiß ≈ #ffd8b0, neutral ≈ #ffe6c8, kaltweiß ≈ #f4f4ff</span>
                  </div>
                </Field>
              )}
            </>
          )}
        </Step>

        <div className="card">
          <strong>Stromaufnahme {TYPE_LABEL[ledType]}</strong>
          <p className="hint">Für das Strombudget. Datenblatt-Werte: WS2812B ≈ 20 mA je Kanal bei 255, SK6812 ≈ 16–20 mA.</p>
          <Field label="mA je Kanal">
            <NumberInput value={cal.ma_per_channel} min={1} max={100} step={1} onChange={(v) => set({ ma_per_channel: v })} />
          </Field>
          <Field label="mA je LED (aus)">
            <NumberInput value={cal.ma_idle} min={0} max={10} step={0.1} onChange={(v) => set({ ma_idle: v })} />
          </Field>
        </div>
      </div>
    </div>
  );
}
