import { Panes } from "../components/Panes";
import { useMemo, useState } from "react";
import { api } from "../api";
import { levelForPwm, pwmOf, SERIES } from "../calibration";
import { LineChart } from "../components/LineChart";
import { SafetyCard } from "../components/Safety";
import { useStore } from "../store";
import type { LedCalibration, LedType } from "../types";
import { Expert, Field, Icon, NumberInput } from "../ui";
import { Help } from "../components/Help";

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
        <p className="hint">Wahrgenommene Helligkeit der Show → Wert, den die LED bekommt.</p>
        <LineChart
          x={full.x}
          series={[{ name: "PWM", color: SERIES[0], values: full.y }]}
          yMax={256}
          height={150}
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
          height={130}
          xFormat={pct}
          yFormat={(v) => v.toFixed(0)}
          xLabel="wahrgenommen"
          yLabel="PWM"
          refLines={[{ y: cal.min_level, label: `Mindeststufe ${cal.min_level}`, color: "#a3abbd" }]}
        />
        <table className="grid" style={{ marginTop: 8 }}>
          <tbody>
            {[
              [0.02, 0.05, 0.1, 0.2],
              [0.3, 0.5, 0.75, 1],
            ].map((row, i) => (
              <tr key={i}>
                {row.map((v) => (
                  <td key={v} style={{ whiteSpace: "nowrap", padding: "4px 6px" }}>
                    <span className="unit">{pct(v)}</span>&nbsp;→&nbsp;{pwmOf(v, cal).toFixed(1)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function SyncCard() {
  const project = useStore((s) => s.project)!;
  const update = useStore((s) => s.updateProject);
  const pb = useStore((s) => s.playback);
  const setPlayback = useStore((s) => s.setPlayback);
  const [bpm, setBpm] = useState(100);
  const syncing = !!pb?.sync;
  return (
    <div className={`card${syncing ? " selected" : ""}`}>
      <div className="row between" style={{ marginBottom: 6 }}>
        <strong>
          Synchronisation Ton ↔ Licht <Help id="sync" />
        </strong>
        <button className={`btn small${syncing ? " active" : ""}`} onClick={async () => setPlayback(await api.sync(!syncing, bpm))}>
          {syncing ? "Sync-Test beenden" : "Sync-Test starten"}
        </button>
      </div>
      <p className="hint">
        Spielt einen Klick auf jeden Beat über die Lautsprecher, alle LEDs blitzen mit (Taktanfang pink). Stell dich an den Betrachterplatz und
        verschiebe die Regler, bis Klick und Blitz gleichzeitig wirken. Kommt das Licht zu früh, Audio-Latenz erhöhen.
      </p>
      {!syncing && (
        <Field label="Tempo">
          <select value={bpm} onChange={(e) => setBpm(+e.target.value)}>
            {[60, 80, 100, 120].map((b) => (
              <option key={b} value={b}>
                {b} BPM
              </option>
            ))}
          </select>
        </Field>
      )}
      <Field label={`Audio-Latenz ${pb?.output.audio_latency_ms ?? 0} ms`}>
        <input
          type="range"
          min={-200}
          max={600}
          step={5}
          value={pb?.output.audio_latency_ms ?? 0}
          onChange={async (e) => setPlayback(await api.output({ audio_latency_ms: +e.target.value }))}
        />
      </Field>
      {project.controllers.map((c) => (
        <Field key={c.id} label={`${c.name} ${c.latency_ms} ms`}>
          <input
            type="range"
            min={-200}
            max={300}
            step={5}
            value={c.latency_ms}
            onChange={(e) =>
              update((p) => {
                p.controllers.find((x) => x.id === c.id)!.latency_ms = +e.target.value;
                return p;
              })
            }
          />
        </Field>
      ))}
      {project.controllers.length > 1 && <p className="hint">Controller-Latenz: reagiert ein Controller später als die anderen, seinen Wert erhöhen.</p>}
    </div>
  );
}

const PATTERN_LABEL: Record<string, string> = {
  steps: "Mindeststufe",
  ramp: "Gleichmäßige Stufen",
  dark: "Dunkle Szenen",
  white: "Weißabgleich",
};

function Step({
  n,
  title,
  help,
  children,
  pattern,
  onShow,
  onStop,
  active,
}: {
  n: number;
  title: string;
  help?: string;
  children: React.ReactNode;
  pattern: string;
  onShow: (kind: string) => void;
  onStop: () => void;
  active: boolean;
}) {
  return (
    <div className={`card cal-step${active ? " running" : ""}`}>
      <div className="row between" style={{ marginBottom: 6 }}>
        <strong className="row" style={{ gap: 8 }}>
          <span className="step-no">{n}</span> {title}
          {help && <Help id={help} />}
        </strong>
        <button
          className={`btn small${active ? " active" : ""}`}
          title={active ? "Testmuster ausschalten" : "Testmuster dieses Schritts auf dem Test-Strip zeigen"}
          onClick={() => (active ? onStop() : onShow(pattern))}
        >
          <Icon name={active ? "stop" : "play"} /> {active ? "Muster beenden" : "Muster zeigen"}
        </button>
      </div>
      {children}
    </div>
  );
}

/** Where the test patterns appear and which one runs – looks different from the steps on purpose. */
function OutputBar({
  live,
  setLive,
  fixtures,
  target,
  setFixture,
  running,
  stop,
}: {
  live: boolean;
  setLive: (live: boolean) => void;
  fixtures: { id: string; name: string }[];
  target: string | null;
  setFixture: (id: string) => void;
  running: string | null;
  stop: () => void;
}) {
  return (
    <div className="cal-output">
      <div className="cal-output-item">
        <span className="unit">
          Testmuster erscheinen <Help id="preview_live" />
        </span>
        <div className="seg" role="group" aria-label="Ausgabe der Testmuster">
          <button className={!live ? "on" : ""} title="Nur in der 3D-Vorschau" onClick={() => setLive(false)}>
            nur in der Vorschau
          </button>
          <button className={live ? "on live" : ""} title="Auch an die echten LEDs senden (gilt für die ganze App, wie „Live“ oben rechts)" onClick={() => setLive(true)}>
            <span className="dot" /> auf den LEDs
          </button>
        </div>
      </div>
      <div className="cal-output-item">
        <span className="unit">auf dem Strip</span>
        <select value={target ?? ""} style={{ width: 200 }} onChange={(e) => setFixture(e.target.value)}>
          {fixtures.length === 0 && <option value="">(kein Strip dieses Typs)</option>}
          {fixtures.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </select>
      </div>
      <div className="cal-output-item grow" style={{ justifyContent: "flex-end" }}>
        {running ? (
          <>
            <span className="cal-running">
              <span className="dot" /> Muster läuft: {PATTERN_LABEL[running] ?? running}
            </span>
            <button className="btn small" onClick={stop}>
              Beenden
            </button>
          </>
        ) : (
          <span className="unit">Kein Muster aktiv</span>
        )}
      </div>
      {!live && (
        <p className="hint" style={{ margin: 0, flexBasis: "100%" }}>
          Zum Kalibrieren „auf den LEDs“ wählen – die Werte lassen sich nur am echten Strip beurteilen, am besten im abgedunkelten Raum.
        </p>
      )}
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
  const stop = async () => setPlayback(await api.test(false, null));
  const setLive = async (on: boolean) => {
    try {
      setPlayback(await api.mode(on ? "live" : "preview"));
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };

  return (
    <Panes id="calibration-v2" sizes={[null, 380]} className="view">
      <div className="pane">
        <div className="row between">
          <h2>
            Kalibrierung <Help id="calibration" />
          </h2>
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
          wahrgenommener Helligkeit und setzt sie in PWM-Werte um. Kalibriere einmal pro LED-Typ: Schritte 1–4 nacheinander durchgehen, jeweils
          das Muster zeigen und am Strip einstellen.
        </p>
        <OutputBar
          live={live}
          setLive={setLive}
          fixtures={fixtures}
          target={target}
          setFixture={setFixture}
          running={testing ? testing.kind : null}
          stop={stop}
        />
        <div className="cal-steps">
        <Step n={1} title="Mindeststufe finden" help="min_level" pattern="steps" onShow={(k) => show(k)} onStop={stop} active={testing?.kind === "steps"}>
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

        <Step n={2} title="Gleichmäßige Stufen" help="curve" pattern="ramp" onShow={(k) => show(k)} onStop={stop} active={testing?.kind === "ramp"}>
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
          <Expert>
            <Field label="Maximum (PWM)">
              <NumberInput integer value={cal.max_level} min={16} max={255} step={1} onChange={(v) => set({ max_level: v })} />
            </Field>
          </Expert>
        </Step>

        <Step n={3} title="Dunkle Szenen" help="dithering" pattern="dark" onShow={(k) => show(k)} onStop={stop} active={testing?.kind === "dark"}>
          <p className="hint">
            Segmente mit 1 %, 2 %, 3 %, 5 %, 7 %, 10 %, 15 %, 20 %. Unter ca. {pct(darkFloor)} liegen die Stufen weniger als einen PWM-Schritt
            auseinander – Dithering verteilt Zwischenwerte räumlich bzw. zeitlich.
          </p>
          <Expert>
            <Field label="Aus unterhalb">
              <div className="row">
                <input type="range" className="grow" min={0} max={0.05} step={0.001} value={cal.cutoff} onChange={(e) => set({ cutoff: +e.target.value })} />
                <span className="unit" style={{ width: 44 }}>
                  {(cal.cutoff * 100).toFixed(1)} %
                </span>
              </div>
            </Field>
          </Expert>
          <Field label="Dithering">
            <select value={cal.dithering} onChange={(e) => set({ dithering: e.target.value as LedCalibration["dithering"] })}>
              <option value="none">aus</option>
              <option value="spatial">räumlich (benachbarte LEDs)</option>
              <option value="temporal">zeitlich (kann bei 50 FPS leicht flimmern)</option>
            </select>
          </Field>
        </Step>

        <Step n={4} title="Weißabgleich" help="white_balance" pattern="white" onShow={(k) => show(k, { level: whiteLevel })} onStop={stop} active={testing?.kind === "white"}>
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

        <SyncCard />

        <SafetyCard />

        <Expert>
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
        </Expert>
        </div>
      </div>

      <div className="pane">
        <h3 style={{ marginTop: 0 }}>Ergebnis: Helligkeitskurve</h3>
        <CurveCharts cal={cal} />
      </div>
    </Panes>
  );
}
