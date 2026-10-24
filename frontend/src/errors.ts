/**
 * Error messages people can act on: a technical message (from the backend, the network or WLED)
 * gets a plain explanation and what to try next.
 */
import { t } from "./i18n";

const RULES: { match: RegExp; hint: () => string }[] = [
  {
    match: /failed to fetch|networkerror|load failed|backend nicht erreichbar/i,
    hint: () => t("Die App antwortet nicht. Läuft sie noch? Starte sie neu (start.ps1 oder die Verknüpfung) und lade die Seite neu."),
  },
  {
    match: /timed? ?out|timeout|connecterror|connect error|unreachable|no route|refused|getaddrinfo|nicht erreichbar/i,
    hint: () =>
      t(
        "Ist der Controller eingeschaltet und im selben WLAN? Stimmt die IP-Adresse (in WLED unter Einstellungen → WLAN)? Schalte dort „WiFi sleep“ aus und versuch es erneut.",
      ),
  },
  {
    match: /claude.*nicht gefunden|claude.*not found/i,
    hint: () => t("Installiere Claude Code (claude.com/claude-code) und starte einmal „claude“ im Terminal, um dich anzumelden."),
  },
  {
    match: /login|not logged|auth|anmelden/i,
    hint: () => t("Starte einmal „claude“ im Terminal und melde dich mit deinem Claude-Konto an."),
  },
  {
    match: /does not support this model|claude update|not have access to.*model/i,
    hint: () => t("Unter „Mit KI“ → „Claude Code aktualisieren“ holst du die neueste Version; sonst läuft die Show mit dem Standardmodell."),
  },
  {
    match: /unsupported image|not a readable image/i,
    hint: () => t("Nimm ein Bild als PNG, JPG, WebP, GIF oder BMP (höchstens 30 MB)."),
  },
  {
    match: /format not recognised|nobackenderror|could not (open|read)|unsupported audio|decode/i,
    hint: () => t("Die Audiodatei ließ sich nicht lesen. Nimm mp3, wav, flac, ogg oder aiff; eine andere Exportversion der Datei hilft oft."),
  },
  {
    match: /no project loaded|kein projekt/i,
    hint: () => t("Öffne oben links ein Projekt oder lege eines an."),
  },
  {
    match: /budget|strom|current/i,
    hint: () => t("Die Show braucht mehr Strom, als das Netzteil liefert. Senke die Helligkeit oder trag unter „Controller“ das richtige Budget ein."),
  },
];

/** A hint what to do about an error message, or null when there is none. */
export function errorHint(message: string): string | null {
  const rule = RULES.find((r) => r.match.test(message));
  return rule ? rule.hint() : null;
}

/** The message with its hint appended. */
export function friendly(message: string): string {
  const hint = errorHint(message);
  return hint ? `${message} – ${hint}` : message;
}
