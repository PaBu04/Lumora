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
  | { type: "heart"; center: Vec3; size: number; normal: Vec3; reference: Vec3 | null; rotate_deg: number }
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
  max_fps?: number | null;
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

export interface FloorplanImage {
  filename: string;
  px_width: number;
  px_height: number;
  x: number;
  y: number;
  width_m: number;
  opacity: number;
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
  floorplan: FloorplanImage | null;
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
  stage?: string | null;
  progress?: number | null;
}

export interface Section {
  start: number;
  end: number;
  name: string;
  label: string;
  energy: number;
  bars?: number;
  /** 2 = the second time this label comes */
  repeat?: number;
  /** 1 (quietest part of the song) .. 5 (most intense) */
  intensity?: number;
  /** the song's climax */
  peak?: boolean;
}

export interface Analysis {
  duration: number;
  bpm: number;
  beats: number[];
  downbeats: number[];
  onsets: number[];
  sections: Section[];
  frame_rate: number;
  features: Record<"rms" | "low" | "mid" | "high" | "onset", number[]> & Partial<Record<InstrumentCurve, number[]>>;
  waveform: number[];
  beat_source: string;
  beat_note: string | null;
  version?: number;
  beats_per_bar?: number;
  beats_edited?: boolean;
  stems?: string | null;
  /** instrument tracks: name -> [time, strength, duration, pitch] */
  tracks?: Record<string, [number, number, number, number][]>;
  /** key and chords: chords are [start, duration, name, degree, strength] */
  /** riffs that come back; track "motif" has them as events (pitch = id) */
  motifs?: { id: number; bars: number; count: number; times: number[]; pitch: number }[];
  /** phrases of the song form: [start s, bars] */
  phrases?: [number, number][];
  harmony?: {
    key: string | null;
    tonic: number | null;
    mode: "major" | "minor" | null;
    confidence: number;
    chords: [number, number, string, string, number][];
  } | null;
}

export type InstrumentCurve =
  | "drums" | "bass" | "vocals" | "other" | "density" | "tension" | "loudness" | "brightness" | "piano" | "guitar";

export interface AiRun {
  id: string;
  project: string;
  prompt: string;
  started: number;
  status: "running" | "done" | "error" | "cancelled";
  events: { kind: "info" | "text" | "tool" | "warn" | "error"; text: string; time: number; detail?: string }[];
  result: string | null;
  error: string | null;
  show_ids: string[];
  turns: number | null;
  duration_s: number | null;
  model: string | null;
  /** the chosen model was refused, Claude Code's default model ran instead */
  fallback?: boolean;
}

export interface Look {
  id: string;
  name: string;
  description: string;
  builtin: boolean;
  beats: number;
  clips: { layer: number; clip: Record<string, unknown> }[];
}

export interface Version {
  id: string;
  time: number;
  source: "ui" | "ai" | "system" | "restore";
  summary: string;
}

export interface AppSettings {
  beat_tracker: "auto" | "librosa" | "beat_this";
  shader_isolation: boolean;
  /** large flashes per second at most (0 = off) */
  flash_limit: number;
  /** the photosensitivity warning was confirmed */
  safety_ack: boolean;
  /** instrument separation */
  stems?: "auto" | "demucs6" | "demucs" | "approx";
  separation?: { four: boolean; six: boolean };
  ai_model?: string;
  beat_this: { installed: boolean; loaded: boolean; error: string | null };
}

export interface Target {
  fixtures?: string[] | null;
  tags?: string[] | null;
  where?: { field: string; min?: number | null; max?: number | null }[];
  view?: "direct" | "indirect" | null;
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
  dynamics?: number;
  /** set on generated starter shows */
  style?: StarterStyle | null;
  layers: Layer[];
}

/** How a generated starter show looks (kept on the show for new variants). */
export interface StarterStyle {
  style: "party" | "calm" | "cinematic" | "minimal";
  colors: "auto" | "cool" | "warm" | "neon" | "nature" | "mono";
  brightness: number;
  strobe: boolean;
  variant: number;
}

export interface ShowSummary {
  id: string;
  name: string;
  song_id: string | null;
  description: string;
  clips: number;
  layers: number;
  style?: StarterStyle | null;
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
  links?: Record<string, { rate: number; sent_fps: number }>;
  speed_testing?: string[];
  sync: { bpm: number; previous: string | null } | null;
  live_input: { device: string; bpm: number; levels: Record<string, number>; time: number } | null;
}

export interface ControllerStatus {
  ok: boolean;
  error?: string;
  warnings: string[];
  hints?: string[];
  sent_fps?: number;
  rate?: number;
  rate_auto?: boolean;
  config?: { buses: { type: number; len: number; pins: number[]; ms: number }[]; max_fps: number } | null;
  info?: WledInfo & { fps?: number; rssi?: number; signal?: number; arch?: string; live?: boolean };
}

export interface SpeedTestResult {
  controller: string;
  measured_fps: number;
  estimated_fps: number | null;
  test_fps: number;
  shown_fps: number;
  loss_pct: number;
  recommended_fps: number;
  rssi: number | null;
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
  params: Record<string, { type: string; default: unknown; description: string; min?: number; max?: number; options?: string[]; dynamic?: boolean }>;
}

export interface PowerReport {
  fps: number;
  times: number[];
  controllers: Record<string, { name: string; peak_ma: number; peak_t: number; mean_ma: number; budget_ma: number | null; limited_seconds?: number; min_scale?: number }>;
  total: { peak_ma: number; peak_t: number; mean_ma: number; budget_ma: number | null; limited_seconds?: number };
  curves: Record<string, number[]>;
  total_curve: number[];
}
