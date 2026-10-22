// Mirrors the backend pydantic models (backend/lsg/model).

export type Vec2 = [number, number];
export type Vec3 = [number, number, number];

export interface Room {
  floor: Vec2[];
  height: number;
}

export interface Viewer {
  position: Vec3;
  yaw_deg: number;
  pitch_deg: number;
}

export type LedType = "ws2812b" | "sk6812" | "sk6812_rgbw";

export type Geometry =
  | { type: "polyline"; points: Vec3[] }
  | { type: "bezier"; points: Vec3[] }
  | {
      type: "arc";
      center: Vec3;
      radius: number;
      normal: Vec3;
      reference: Vec3 | null;
      start_deg: number;
      sweep_deg: number;
    }
  | { type: "circle"; center: Vec3; radius: number; normal: Vec3; reference: Vec3 | null; start_deg: number }
  | {
      type: "matrix";
      origin: Vec3;
      col_dir: Vec3;
      row_dir: Vec3;
      cols: number;
      rows: number;
      pitch: number;
      serpentine: boolean;
      column_major: boolean;
    };

export type GeometryType = Geometry["type"];

export interface Fixture {
  id: string;
  name: string;
  geometry: Geometry;
  led_type: LedType;
  leds_per_meter: number;
  led_count: number | null;
  reverse: boolean;
  tags: string[];
}

export interface FixtureMapping {
  fixture_id: string;
  start: number;
  fixture_offset: number;
  count: number | null;
}

export interface Controller {
  id: string;
  name: string;
  host: string;
  port: number;
  mac: string | null;
  rgbw: boolean;
  latency_ms: number;
  budget_ma: number | null;
  mappings: FixtureMapping[];
}

export interface LedCalibration {
  curve: "cie" | "gamma";
  gamma: number;
  min_level: number;
  max_level: number;
  cutoff: number;
  white_balance: [number, number, number];
  dithering: "none" | "spatial" | "temporal";
  white_mode: "off" | "min" | "color";
  white_color: string;
  ma_per_channel: number;
  ma_idle: number;
}

export interface PowerSettings {
  total_budget_ma: number | null;
  volts: number;
}

export interface Project {
  schema_version: number;
  name: string;
  room: Room;
  viewer: Viewer;
  fixtures: Fixture[];
  controllers: Controller[];
  calibration: Record<LedType, LedCalibration>;
  power: PowerSettings;
}

export interface LedData {
  count: number;
  positions: number[];
  fixtures: { id: string; start: number; count: number; length: number }[];
}

export interface Song {
  id: string;
  title: string;
  artist: string;
  filename: string;
  duration: number;
  status: "pending" | "running" | "done" | "error";
  error: string | null;
}

export interface Section {
  start: number;
  end: number;
  name: string;
  label: string;
  energy: number;
}

export interface Analysis {
  duration: number;
  bpm: number;
  beats: number[];
  downbeats: number[];
  onsets: number[];
  sections: Section[];
  frame_rate: number;
  features: Record<"rms" | "low" | "mid" | "high" | "onset", number[]>;
  waveform: number[];
  beat_source: string;
  beat_note: string | null;
}

export interface AppSettings {
  beat_tracker: "auto" | "librosa" | "beat_this";
  beat_this: { installed: boolean; loaded: boolean; error: string | null };
}

export interface Target {
  fixtures?: string[] | null;
  tags?: string[] | null;
  where?: { field: string; min?: number | null; max?: number | null }[];
  invert?: boolean;
}

export interface Clip {
  id: string;
  start: number;
  end: number;
  effect: string;
  params: Record<string, unknown>;
  target: Target;
  blend: string;
  opacity: number;
  fade_in: number;
  fade_out: number;
}

export interface Layer {
  id: string;
  name: string;
  enabled: boolean;
  opacity: number;
  clips: Clip[];
}

export interface Show {
  id: string;
  name: string;
  description: string;
  song_id: string | null;
  duration: number | null;
  master: number;
  layers: Layer[];
}

export interface ShowSummary {
  id: string;
  name: string;
  song_id: string | null;
  description: string;
  clips: number;
  layers: number;
}

export interface Issue {
  severity: "error" | "warning";
  clip: string | null;
  layer: string | null;
  message: string;
}

export interface PlaybackState {
  type: "state";
  project: string | null;
  show: string | null;
  show_name: string | null;
  song: string | null;
  playing: boolean;
  position: number;
  duration: number;
  mode: "preview" | "live";
  test: { fixture: string | null; kind: string; params: Record<string, unknown> } | null;
  led_count: number;
  fps: number;
  render_ms: number;
  clip_errors: Record<string, string>;
  output: { brightness: number; audio_latency_ms: number };
  power: {
    total_ma: number;
    total_requested_ma: number;
    total_budget_ma: number | null;
    controllers: Record<string, { ma: number; requested_ma: number; scale: number; budget_ma: number | null }>;
    peak_ma: Record<string, number>;
  };
  controller_errors: Record<string, string>;
  controller_status: Record<string, ControllerStatus>;
  sync: { bpm: number; previous: string | null } | null;
}

export interface ControllerStatus {
  ok: boolean;
  error?: string;
  warnings: string[];
  info?: WledInfo & { fps?: number; rssi?: number; signal?: number; arch?: string; live?: boolean };
}

export interface WledInfo {
  host: string;
  name: string;
  version?: string;
  mac?: string;
  led_count?: number;
  rgbw?: boolean;
  error?: string;
}

export interface EffectInfo {
  id: string;
  name: string;
  description: string;
  params: Record<string, { type: string; default: unknown; description: string; min?: number; max?: number; options?: string[] }>;
}

export interface PowerReport {
  fps: number;
  times: number[];
  controllers: Record<string, { name: string; peak_ma: number; peak_t: number; mean_ma: number; budget_ma: number | null; limited_seconds?: number; min_scale?: number }>;
  total: { peak_ma: number; peak_t: number; mean_ma: number; budget_ma: number | null; limited_seconds?: number };
  curves: Record<string, number[]>;
  total_curve: number[];
}
