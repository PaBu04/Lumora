import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";
import { lang } from "./i18n";
import { startDomTranslation } from "./i18n/dom";
import { connectSocket } from "./ws";

connectSocket();
if (lang === "en") startDomTranslation();

// sliders show their value as a filled track (Chromium has no ::progress pseudo element):
// keep the --fill custom property in sync, also for values React sets without an input event
function syncSliders() {
  for (const el of document.querySelectorAll<HTMLInputElement>('input[type="range"]')) {
    const lo = Number(el.min || 0),
      hi = Number(el.max || 100);
    const fill = `${hi > lo ? ((Number(el.value) - lo) / (hi - lo)) * 100 : 0}%`;
    if (el.style.getPropertyValue("--fill") !== fill) el.style.setProperty("--fill", fill);
  }
}
document.addEventListener("input", syncSliders, true);
setInterval(syncSliders, 250);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
