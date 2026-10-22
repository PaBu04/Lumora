import { create } from "zustand";
import { api } from "./api";
import type { AiRun, LedData, PlaybackState, Project, ShowSummary, Song } from "./types";

export type Tab = "room" | "fixtures" | "devices" | "calibration" | "songs" | "shows" | "ai";

interface Toast {
  id: number;
  message: string;
  kind: "info" | "error" | "success";
}

interface AppStore {
  tab: Tab;
  projects: { slug: string; name: string; fixtures: number; controllers: number }[];
  slug: string | null;
  project: Project | null;
  leds: LedData | null;
  projectError: string | null;
  saving: boolean;
  songs: Song[];
  shows: ShowSummary[];
  playback: PlaybackState | null;
  selectedFixture: string | null;
  selectedPoint: number | null;
  toasts: Toast[];
  showRevision: number;
  aiRun: AiRun | null;
  setAiRun: (r: AiRun | null) => void;
  past: Project[];
  future: Project[];
  undoScope: "project" | "show";
  undo: () => void;
  redo: () => void;
  setUndoScope: (s: "project" | "show") => void;

  setTab: (t: Tab) => void;
  notify: (message: string, kind?: Toast["kind"]) => void;
  dismiss: (id: number) => void;
  init: () => Promise<void>;
  openProject: (slug: string) => Promise<void>;
  createProject: (name: string) => Promise<void>;
  updateProject: (fn: (p: Project) => Project) => void;
  reloadProject: () => Promise<void>;
  refreshLeds: () => Promise<void>;
  refreshSongs: () => Promise<void>;
  refreshShows: () => Promise<void>;
  refreshProjects: () => Promise<void>;
  setPlayback: (s: PlaybackState) => void;
  selectFixture: (id: string | null, point?: number | null) => void;
  bumpShowRevision: () => void;
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;
let toastId = 0;
let lastPush = 0;
const HISTORY_LIMIT = 100;
const COALESCE_MS = 700; // rapid edits (typing, sliders) become one undo step

function scheduleSave(get: () => AppStore, set: (p: Partial<AppStore>) => void) {
  if (saveTimer) clearTimeout(saveTimer);
  set({ saving: true });
  saveTimer = setTimeout(async () => {
    saveTimer = null;
    const { slug, project } = get();
    if (!slug || !project) return;
    try {
      await api.saveProject(slug, project);
      set({ projectError: null, saving: false });
      await get().refreshLeds();
    } catch (e) {
      set({ projectError: (e as Error).message, saving: false });
    }
  }, 350);
}

export const useStore = create<AppStore>((set, get) => ({
  tab: (localStorage.getItem("lsg.tab") as Tab) || "room",
  projects: [],
  slug: null,
  project: null,
  leds: null,
  projectError: null,
  saving: false,
  songs: [],
  shows: [],
  playback: null,
  selectedFixture: null,
  selectedPoint: null,
  toasts: [],
  showRevision: 0,
  aiRun: null,
  setAiRun: (aiRun) => set({ aiRun }),
  past: [],
  future: [],
  undoScope: "project",

  setTab: (tab) => {
    try {
      localStorage.setItem("lsg.tab", tab);
    } catch {
      /* storage unavailable */
    }
    set({ tab });
  },

  notify: (message, kind = "info") => {
    const id = ++toastId;
    set((s) => ({ toasts: [...s.toasts, { id, message, kind }] }));
    setTimeout(() => get().dismiss(id), kind === "error" ? 8000 : 3500);
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  init: async () => {
    const [{ projects, active }, songs, playback] = await Promise.all([api.projects(), api.songs(), api.playback()]);
    set({ projects, songs, playback });
    const slug = active ?? projects[0]?.slug;
    if (slug) await get().openProject(slug);
  },

  refreshProjects: async () => {
    const { projects } = await api.projects();
    set({ projects });
  },

  openProject: async (slug) => {
    const [project, leds, shows] = await Promise.all([api.project(slug), api.leds(slug), api.shows(slug)]);
    set({ slug, project, leds, shows, projectError: null, selectedFixture: null, selectedPoint: null, past: [], future: [] });
    await api.activate(slug);
  },

  createProject: async (name) => {
    const { slug } = await api.createProject(name);
    await get().refreshProjects();
    await get().openProject(slug);
    get().notify(`Projekt „${name}" angelegt`, "success");
  },

  updateProject: (fn) => {
    const { project, slug, past } = get();
    if (!project || !slug) return;
    const next = fn(structuredClone(project));
    const now = Date.now();
    const push = now - lastPush > COALESCE_MS;
    lastPush = now;
    set({ project: next, future: [], past: push ? [...past, project].slice(-HISTORY_LIMIT) : past });
    scheduleSave(get, set);
  },

  undo: () => {
    const { past, future, project } = get();
    if (!project || past.length === 0) return;
    lastPush = 0;
    set({ project: past[past.length - 1], past: past.slice(0, -1), future: [project, ...future].slice(0, HISTORY_LIMIT) });
    scheduleSave(get, set);
    get().notify("Rückgängig");
  },

  redo: () => {
    const { past, future, project } = get();
    if (!project || future.length === 0) return;
    lastPush = 0;
    set({ project: future[0], future: future.slice(1), past: [...past, project].slice(-HISTORY_LIMIT) });
    scheduleSave(get, set);
    get().notify("Wiederholt");
  },

  setUndoScope: (undoScope) => set({ undoScope }),

  reloadProject: async () => {
    const { slug } = get();
    if (!slug || saveTimer || get().saving) return;
    const [project, leds] = await Promise.all([api.project(slug), api.leds(slug)]);
    // a change from elsewhere (restore, AI) invalidates the local undo stack
    const external = JSON.stringify(project) !== JSON.stringify(get().project);
    set(external ? { project, leds, past: [], future: [] } : { project, leds });
  },

  refreshLeds: async () => {
    const { slug } = get();
    if (slug) set({ leds: await api.leds(slug) });
  },
  refreshSongs: async () => set({ songs: await api.songs() }),
  refreshShows: async () => {
    const { slug } = get();
    if (slug) set({ shows: await api.shows(slug) });
  },
  setPlayback: (playback) => set({ playback }),
  selectFixture: (id, point = null) => set({ selectedFixture: id, selectedPoint: point }),
  bumpShowRevision: () => set((s) => ({ showRevision: s.showRevision + 1 })),
}));
