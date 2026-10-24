/**
 * Interface language. The German text is the key: t("Speichern") returns it in German and its
 * English translation (i18n/en.ts) in English, so components stay readable. Placeholders: t("{n} Clips", { n }).
 * Changing the language reloads the page.
 */
import { EN } from "./i18n/en";

export type Lang = "de" | "en";

function initial(): Lang {
  try {
    const saved = localStorage.getItem("lumora.lang");
    if (saved === "de" || saved === "en") return saved;
  } catch {
    /* no storage */
  }
  return navigator.language?.toLowerCase().startsWith("de") ? "de" : "en";
}

export const lang: Lang = initial();

export function setLang(l: Lang): void {
  try {
    localStorage.setItem("lumora.lang", l);
  } catch {
    /* no storage */
  }
  location.reload();
}

export function t(de: string, vars?: Record<string, string | number>): string {
  let s = lang === "en" ? (EN[de] ?? de) : de;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v));
  return s;
}

/** Pick the text for the current language from a bilingual pair. */
export function tr(text: { de: string; en: string }): string {
  return lang === "en" ? text.en : text.de;
}
