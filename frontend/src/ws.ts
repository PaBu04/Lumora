import { useStore } from "./store";

/** Latest rendered frame from the backend. Read in render loops, never put into React state. */
export const liveFrame = {
  t: 0,
  count: 0,
  colors: new Uint8Array(0),
  version: 0,
};

let socket: WebSocket | null = null;

export function connectSocket(): void {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${proto}://${location.host}/ws`);
  socket.binaryType = "arraybuffer";

  socket.onmessage = (ev) => {
    if (ev.data instanceof ArrayBuffer) {
      const view = new DataView(ev.data);
      liveFrame.t = view.getFloat64(0, true);
      liveFrame.count = view.getUint32(8, true);
      liveFrame.colors = new Uint8Array(ev.data, 12, liveFrame.count * 3);
      liveFrame.version++;
      return;
    }
    const msg = JSON.parse(ev.data);
    const store = useStore.getState();
    if (msg.type === "state") {
      store.setPlayback(msg);
    } else if (msg.type === "event") {
      switch (msg.kind) {
        case "project_changed":
          if (msg.project === store.slug) void store.reloadProject();
          break;
        case "show_changed":
          if (msg.project === store.slug) {
            void store.refreshShows();
            store.bumpShowRevision();
          }
          break;
        case "song_changed":
          void store.refreshSongs();
          break;
        case "shaders_changed":
          store.bumpShowRevision();
          break;
        case "ai":
          store.setAiRun(msg.run);
          break;
      }
    }
  };

  socket.onclose = () => {
    setTimeout(connectSocket, 1000);
  };
}
