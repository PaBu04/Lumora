import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import type { Show } from "../types";

const LIMIT = 100;
const SAVE_MS = 400;

/** Local editable copy of a show with undo/redo and debounced saving. */
export function useShowEditor(slug: string | null, showId: string | null) {
  const rev = useStore((s) => s.showRevision);
  const notify = useStore((s) => s.notify);
  const refreshShows = useStore((s) => s.refreshShows);
  const [show, setShow] = useState<Show | null>(null);
  const past = useRef<Show[]>([]);
  const future = useRef<Show[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef<Show | null>(null);
  const lastSaved = useRef<string>("");

  // load / reload when the show changes elsewhere (AI, restore) - unless local edits are pending
  useEffect(() => {
    if (!slug || !showId) {
      setShow(null);
      latest.current = null;
      return;
    }
    if (pending.current) return;
    api
      .show(slug, showId)
      .then((s) => {
        const json = JSON.stringify(s);
        if (json === lastSaved.current && latest.current?.id === s.id) return; // our own save echoed back
        const external = latest.current?.id === s.id;
        latest.current = s;
        lastSaved.current = json;
        setShow(s);
        if (!external) {
          past.current = [];
          future.current = [];
        }
      })
      .catch(() => setShow(null));
  }, [slug, showId, rev]);

  const save = useCallback(() => {
    if (pending.current) clearTimeout(pending.current);
    setSaving(true);
    pending.current = setTimeout(async () => {
      pending.current = null;
      const s = latest.current;
      if (!slug || !s) return;
      try {
        lastSaved.current = JSON.stringify(s);
        await api.saveShow(slug, s);
        setError(null);
        void refreshShows();
      } catch (e) {
        setError((e as Error).message);
        notify(`Speichern fehlgeschlagen: ${(e as Error).message}`, "error");
      } finally {
        setSaving(false);
      }
    }, SAVE_MS);
  }, [slug, notify, refreshShows]);

  /** Apply an edit (one undo step). */
  const apply = useCallback(
    (fn: (s: Show) => Show) => {
      const cur = latest.current;
      if (!cur) return;
      const next = fn(cur);
      if (next === cur) return;
      latest.current = next;
      past.current = [...past.current, cur].slice(-LIMIT);
      future.current = [];
      setShow(next);
      save();
    },
    [save],
  );

  const undo = useCallback(() => {
    const cur = latest.current;
    if (!past.current.length || !cur) return;
    const prev = past.current[past.current.length - 1];
    past.current = past.current.slice(0, -1);
    future.current = [cur, ...future.current].slice(0, LIMIT);
    latest.current = prev;
    setShow(prev);
    save();
  }, [save]);

  const redo = useCallback(() => {
    const cur = latest.current;
    if (!future.current.length || !cur) return;
    const next = future.current[0];
    future.current = future.current.slice(1);
    past.current = [...past.current, cur].slice(-LIMIT);
    latest.current = next;
    setShow(next);
    save();
  }, [save]);

  // flush on unmount
  useEffect(
    () => () => {
      if (pending.current && slug && latest.current) {
        clearTimeout(pending.current);
        void api.saveShow(slug, latest.current);
      }
    },
    [slug],
  );

  return { show, apply, undo, redo, canUndo: past.current.length > 0, canRedo: future.current.length > 0, saving, error };
}

export type ShowEditor = ReturnType<typeof useShowEditor>;
