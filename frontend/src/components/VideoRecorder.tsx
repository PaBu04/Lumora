import { useRef, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import { useStore } from "../store";
import { formatTime } from "../ui";
import { liveFrame } from "../ws";

type Range = "all" | "30" | "rest";

function pickMime(): string {
  for (const m of ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"]) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(m)) return m;
  }
  return "";
}

/**
 * Records the 3D preview as a video with the song (WebM): the canvas as it is shown (with the LED
 * glow) and the song's audio. Runs in real time. The audio starts when the first frame of the start
 * arrives, so light and sound stay together whatever audio latency is set for the speakers.
 */
export function VideoRecorder({ songId, duration, name }: { songId: string | null; duration: number; name: string }) {
  const setPlayback = useStore((s) => s.setPlayback);
  const notify = useStore((s) => s.notify);
  const [range, setRange] = useState<Range>("all");
  const [state, setState] = useState<{ t: number; end: number } | null>(null);
  const stopRef = useRef<() => void>(() => undefined);

  const record = async () => {
    const canvas = document.querySelector<HTMLCanvasElement>(".canvas-wrap canvas");
    const mime = pickMime();
    if (!canvas || !mime) return notify(t("Videoaufnahme wird von diesem Browser nicht unterstützt."), "error");
    const pos = useStore.getState().playback?.position ?? 0;
    const start = range === "all" ? 0 : pos;
    const end = range === "30" ? Math.min(duration, start + 30) : duration;
    if (end - start < 1) return notify(t("Am Ende der Show gibt es nichts mehr aufzunehmen."), "error");

    const tracks = [...canvas.captureStream(30).getVideoTracks()];
    let audio: HTMLAudioElement | null = null;
    let ctx: AudioContext | null = null;
    if (songId) {
      audio = new Audio(`/api/songs/${songId}/audio`);
      audio.crossOrigin = "anonymous";
      audio.preload = "auto";
      ctx = new AudioContext();
      const dest = ctx.createMediaStreamDestination();
      ctx.createMediaElementSource(audio).connect(dest); // recorded, not played: the speakers get the app's own playback
      tracks.push(...dest.stream.getAudioTracks());
      await new Promise((ok) => {
        audio!.addEventListener("loadedmetadata", ok, { once: true });
        audio!.load();
      });
      audio.currentTime = start;
    }
    const chunks: Blob[] = [];
    const rec = new MediaRecorder(new MediaStream(tracks), { mimeType: mime, videoBitsPerSecond: 8_000_000 });
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    let raf = 0;
    let stopped = false;
    const stop = async () => {
      if (stopped) return;
      stopped = true;
      cancelAnimationFrame(raf);
      audio?.pause();
      setPlayback(await api.pause());
      if (rec.state !== "inactive") rec.stop();
    };
    stopRef.current = () => void stop();
    rec.onstop = () => {
      void ctx?.close();
      tracks.forEach((tr) => tr.stop());
      setState(null);
      const blob = new Blob(chunks, { type: "video/webm" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${name.replace(/[^\w\- ]+/g, "").trim() || "Show"}.webm`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 60_000);
      notify(t("Video gespeichert ({mb} MB)", { mb: (blob.size / 1e6).toFixed(1) }), "success");
    };

    setPlayback(await api.pause());
    setPlayback(await api.seek(start));
    setState({ t: start, end });
    rec.start(1000);
    setPlayback(await api.play());
    let audioStarted = !audio;
    const tick = () => {
      const now = liveFrame.t;
      if (!audioStarted && now >= start + 0.01) {
        audioStarted = true;
        audio!.currentTime = now;
        void audio!.play();
      }
      setState({ t: now, end });
      if (now >= end - 0.02 || (audio && audio.ended)) return void stop();
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
  };

  return (
    <div className="video-rec">
      <div className="row">
        <select value={range} disabled={!!state} onChange={(e) => setRange(e.target.value as Range)} style={{ flex: "1 1 150px", width: "auto" }}>
          <option value="all">{t("ganze Show")}</option>
          <option value="rest">{t("ab Abspielposition")}</option>
          <option value="30">{t("30 s ab Abspielposition")}</option>
        </select>
        {state ? (
          <button className="btn small danger" onClick={() => stopRef.current()}>
            {t("Stopp")} · {formatTime(Math.max(0, state.t))} / {formatTime(state.end)}
          </button>
        ) : (
          <button className="btn small" onClick={() => void record()}>
            {t("Video aufnehmen")}
          </button>
        )}
      </div>
      <p className="hint" style={{ margin: "6px 0 0" }}>
        {t("Nimmt die 3D-Vorschau mit Ton als WebM auf, in Echtzeit. Tipp: vorher „Betrachter-Sicht“ einschalten.")}
      </p>
    </div>
  );
}
