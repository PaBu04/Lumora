import type {
  AiRun,
  Analysis,
  AppSettings,
  EffectInfo,
  Fixture,
  Issue,
  LedData,
  PlaybackState,
  PowerReport,
  Project,
  Show,
  ShowSummary,
  Song,
  Version,
  WledInfo,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, url: string, body?: unknown, raw = false): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (typeof body === "string") {
    init.body = body;
    (init.headers as Record<string, string>)["Content-Type"] = "text/plain";
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg);
  }
  if (raw) return (await res.text()) as T;
  return (await res.json()) as T;
}

const get = <T>(url: string) => request<T>("GET", url);
const post = <T>(url: string, body?: unknown) => request<T>("POST", url, body);
const put = <T>(url: string, body?: unknown) => request<T>("PUT", url, body);
const del = <T>(url: string) => request<T>("DELETE", url);

export const api = {
  projects: () =>
    get<{ projects: { slug: string; name: string; fixtures: number; controllers: number }[]; active: string | null }>(
      "/api/projects",
    ),
  createProject: (name: string) => post<{ slug: string; project: Project }>("/api/projects", { name }),
  project: (slug: string) => get<Project>(`/api/projects/${slug}`),
  saveProject: (slug: string, p: Project) => put<Project>(`/api/projects/${slug}`, p),
  deleteProject: (slug: string) => del(`/api/projects/${slug}`),
  activate: (slug: string) => post<PlaybackState>(`/api/projects/${slug}/activate`),
  leds: (slug: string) => get<LedData>(`/api/projects/${slug}/leds`),
  fixturePreview: (f: Fixture) => post<{ count: number; length: number }>("/api/fixtures/preview", f),

  shows: (slug: string) => get<ShowSummary[]>(`/api/projects/${slug}/shows`),
  createShow: (slug: string, name: string, song_id: string | null, template: string) =>
    post<Show>(`/api/projects/${slug}/shows`, { name, song_id, template }),
  show: (slug: string, id: string) => get<Show>(`/api/projects/${slug}/shows/${id}`),
  saveShow: (slug: string, show: Show) => put<Show>(`/api/projects/${slug}/shows/${show.id}`, show),
  deleteShow: (slug: string, id: string) => del(`/api/projects/${slug}/shows/${id}`),
  showVersions: (slug: string, id: string) => get<Version[]>(`/api/projects/${slug}/shows/${id}/versions`),
  restoreShowVersion: (slug: string, id: string, vid: string) => post<Show>(`/api/projects/${slug}/shows/${id}/versions/${vid}/restore`),
  projectVersions: (slug: string) => get<Version[]>(`/api/projects/${slug}/versions`),
  restoreProjectVersion: (slug: string, vid: string) => post<Project>(`/api/projects/${slug}/versions/${vid}/restore`),
  validate: (slug: string, id: string) => post<Issue[]>(`/api/projects/${slug}/shows/${id}/validate`),
  power: (slug: string, id: string, fps = 2) => get<PowerReport>(`/api/projects/${slug}/shows/${id}/power?fps=${fps}`),

  shaders: (slug: string) =>
    get<{ shaders: string[]; errors: Record<string, string>; api: string }>(`/api/projects/${slug}/shaders`),
  shader: (slug: string, name: string) => request<string>("GET", `/api/projects/${slug}/shaders/${name}`, undefined, true),
  saveShader: (slug: string, name: string, code: string) => put(`/api/projects/${slug}/shaders/${name}`, code),
  deleteShader: (slug: string, name: string) => del(`/api/projects/${slug}/shaders/${name}`),

  songs: () => get<Song[]>("/api/songs"),
  uploadSong: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return post<Song>("/api/songs", fd);
  },
  demoSong: (bpm = 124) => post<Song>(`/api/songs/demo?bpm=${bpm}`),
  updateSong: (id: string, patch: { title?: string; artist?: string }) => request<Song>("PATCH", `/api/songs/${id}`, patch),
  deleteSong: (id: string) => del(`/api/songs/${id}`),
  analysis: (id: string) => get<Analysis>(`/api/songs/${id}/analysis`),
  reanalyse: (id: string) => post(`/api/songs/${id}/analyse`),
  scaleTempo: (id: string, factor: number) => post<{ bpm: number; beats: number }>(`/api/songs/${id}/tempo`, { factor }),

  aiStatus: () => get<{ claude: { installed: boolean; version: string | null }; run: AiRun | null }>("/api/ai/status"),
  aiRun: (body: { project: string; prompt: string; song_id: string | null; show_name: string; show_id: string | null }) =>
    post<AiRun>("/api/ai/run", body),
  aiCancel: () => post<AiRun | null>("/api/ai/cancel"),
  settings: () => get<AppSettings>("/api/settings"),
  saveSettings: (s: Partial<Pick<AppSettings, "beat_tracker">>) => put<AppSettings>("/api/settings", s),
  effects: () => get<{ effects: EffectInfo[]; palettes: Record<string, string[]>; shader_api: string }>("/api/effects"),

  playback: () => get<PlaybackState>("/api/playback"),
  load: (project: string, show: string | null) => post<PlaybackState>("/api/playback/load", { project, show }),
  play: () => post<PlaybackState>("/api/playback/play"),
  pause: () => post<PlaybackState>("/api/playback/pause"),
  stop: () => post<PlaybackState>("/api/playback/stop"),
  seek: (t: number) => post<PlaybackState>("/api/playback/seek", { t }),
  mode: (mode: "preview" | "live") => post<PlaybackState>("/api/playback/mode", { mode }),
  output: (o: { brightness?: number; audio_latency_ms?: number }) =>
    post<PlaybackState>("/api/playback/output", o),
  test: (enabled: boolean, fixture_id: string | null, kind = "identify", params: Record<string, unknown> = {}) =>
    post<PlaybackState>("/api/playback/test", { enabled, fixture_id, kind, params }),

  liveDevices: () => get<{ index: number; name: string; channels: number; default: boolean }[]>("/api/live/devices"),
  liveInput: (enabled: boolean, show_id: string | null = null, device: number | null = null) =>
    post<PlaybackState>("/api/playback/live-input", { enabled, show_id, device }),
  sync: (enabled: boolean, bpm = 100) => post<PlaybackState>("/api/playback/sync", { enabled, bpm }),
  discover: (seconds = 3) => get<WledInfo[]>(`/api/devices/discover?seconds=${seconds}`),
  deviceInfo: (host: string) => get<WledInfo>(`/api/devices/info?host=${encodeURIComponent(host)}`),
};
