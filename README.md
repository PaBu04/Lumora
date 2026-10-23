# Neopixel Light Show Generator

Musiksynchrone Lichtshows für adressierbare LEDs (WS2812B, SK6812 RGB/RGBW) an WLED-Controllern –
mit 3D-Raummodell, Betrachterposition, Songanalyse, grafischem Timeline-Editor und KI-Unterstützung
(eingebaut über Claude Code oder als MCP-Server für eigene KI-Clients).

## Funktionen

**Raum und LEDs**
- Grundriss als 2D-Skizze (Ecken ziehen, einfügen, löschen, Vorlagen) plus Raumhöhe – oder ein Foto /
  einen Bauplan hochladen, Maßstab über zwei Punkte festlegen und die Ecken nachzeichnen.
- LED-Strips als Linien, Bezier-Kurven, Bögen, Kreise und Matrizen; Presets (Deckenumrandung, Wandleiste,
  Eckstreifen, Deckenring, Wand-Matrix, Herz mit Größe und Drehung); Punkte per 3D-Gizmo verschieben (rastet an
  Wänden, Boden, Decke ein),
  ganze Strips verschieben, Punkte per Drag-and-Drop umsortieren.
- 3D-Ansicht perspektivisch oder orthografisch, Achsenkreuz (X/Y/Z) zum Orientieren.
- Betrachter (im Reiter *Raum*) mit Position und Blickrichtung: Effekte können „von links nach rechts durchs
  Blickfeld“ laufen.
- Rückgängig/Wiederholen (Strg+Z / Strg+Y) und ein Versionsverlauf mit Wiederherstellen.
- Neuer Raum leer oder als Kopie eines bestehenden (Raum, Strips, Controller, Kalibrierung, wahlweise mit Shows).

**Hardware**
- WLED-Controller per mDNS finden, Strips Pixelbereichen zuordnen, Testmuster, Live-Ausgabe per DDP (~50 FPS).
- **Bildrate pro Controller:** Ein WLED kann nur so viele Bilder zeigen, wie seine Datenleitungen schaffen
  (WS2812B: ~30 µs pro LED und Pin – 873 LEDs an einem Pin ≈ 32 FPS). Die App liest dazu die LED-Konfiguration
  aus WLED, schickt jedem Controller gleichmäßig getaktet knapp unter seinem Maximum und lässt unveränderte
  Bilder weg (nur Keep-alive). *Geschwindigkeit messen* ermittelt die echte Rate und Paketverluste; die
  Bildrate lässt sich auch von Hand festlegen.
- Statusüberwachung: erreichbar, WLED-Version, gesendete und angezeigte FPS, mögliches Maximum, WLAN-Signal,
  Hinweise (z. B. Strip auf mehrere Datenpins aufteilen, WLAN-Energiesparen aus).
- **Kalibrierung:** Shows rechnen in *wahrgenommener* Helligkeit (0,5 sieht halb so hell aus). Eine Kurve
  (CIE L* oder Gamma) setzt das in PWM um; Mindeststufe, Abschaltschwelle, Weißabgleich, RGBW-Weißmischung und
  räumliches/zeitliches Dithering sorgen dafür, dass dunkle und helle Szenen gut rüberkommen. Ein Assistent zeigt
  Testmuster direkt auf den LEDs (rohe PWM-Stufen, gleichmäßige Stufen, Dunkelstufen, Weiß).
- **Strombudget** pro Controller und Netzteil: Stromschätzung aus den tatsächlichen PWM-Werten, automatische
  Drosselung, Stromverlauf und Warnungen in der Show-Prüfung.
- **Synchronisation:** Sync-Test (Klick auf jeden Beat + LED-Blitz) zum Einstellen von Audio- und Controller-Latenz.

**Musik**
- Songs hochladen (mp3/wav/flac/ogg); Analyse von Tempo, Beats, Takten (3/4 oder 4/4), Abschnitten
  (Intro/Strophe/Refrain/Break/Bridge/Build-up/Drop/Outro) und Pegeln je Frequenzband; Tempo-Korrektur ×2/÷2 und
  auf 0,1 BPM genau (bleibt bei einer neuen Analyse erhalten).
- **Instrumente:** Der Song wird mit dem KI-Modell *Hybrid Demucs* in Schlagzeug, Bass, Gesang und den Rest
  (Keys, Synths, Gitarren) getrennt (~1 Minute pro Song auf der CPU). Daraus entstehen Instrumentenspuren:
  Kick/Snare/Hi-Hat/Crash mit Anschlagstärke (Wirbel und Fills so schnell wie gespielt, nicht im Raster),
  Bass-, Gesangs- und Lead-Noten mit Tonhöhe und Länge, Gesangsphrasen, Drum-Fills, Build-ups, Drops und
  Passagen ohne Schlagzeug, dazu Lautstärkekurven je Instrument. Ohne PyTorch werden Schlagzeug/Bass/Rest
  geschätzt (kein Gesang).
- Songs lassen sich im Reiter *Songs* abspielen (auch langsamer): Ein Positionsanzeiger läuft über Waveform und
  Instrumentenspuren (ganzer Song oder mitlaufender 30-/10-s-Ausschnitt), und Anzeigen leuchten auf, sobald Kick,
  Snare, Bass, Gesang, Fill oder Drop erkannt sind – so lässt sich die Analyse mit dem Ohr prüfen.
- Genauere Beat- und Takterkennung mit dem neuronalen Modell *beat_this*; beide Modelle kommen mit
  `pip install -e ".[ml]"` (PyTorch, ca. 1 GB; Modelldaten werden beim ersten Mal geladen).
- **Live-Eingang:** ohne vorbereiteten Song reagiert die Show „Live (Mikrofon)“ in Echtzeit auf Tempo, Bass und Höhen –
  wahlweise auf den Ton, den der PC gerade abspielt (Browser, Spotify …; Windows-Loopback), oder auf ein Mikrofon.

**Shows**
- Grafischer Timeline-Editor: Clips ziehen, kürzen, an Beats/Takte einrasten, Mehrfachauswahl, Kopieren/Einfügen,
  Ebenen; Inspektor mit Reglern, Farbwählern, Paletten und den Modi Wert / Audio / LFO / Keyframes; Ziel-Editor.
- 18 Effekte, darunter *Hits* (kurze LED-Segmente leuchten auf Schlägen auf), *Notes* (Noten eines Instruments,
  Position = Tonhöhe, leuchtet so lange wie der Ton), *Sweep* (ein Lichtband läuft durch den ganzen Raum) und
  *Rise* (Build-up bis zum Drop). Effekte lassen sich von jeder Instrumentenspur auslösen (Kick, Snare, Bass,
  Gesang, Lead, Fill, Drop …) und folgen der Anschlagstärke; Auslöser *once* macht aus einem Clip einen
  einmaligen Cue. Muster lassen sich in Metern entlang der Strips legen (Achse `s`).
- **Cues einspielen:** Während der Song läuft, per Klick oder Taste 1–7 einzelne Effekte setzen (Blitz,
  Raumblitz, Ring, Wischer, Funkeln, Rise bis zum nächsten Drop) – rasten auf den nächsten Schlag ein. Eine
  Musik-Zeile in der Timeline zeigt Drops, Build-ups, Fills und Gesang; Clips rasten dort ein.
- **Dynamik:** leise Stellen des Songs dunkeln die ganze Show ab, laute bleiben hell.
- Der Betrachter sieht nicht alle LEDs: Ziele „im Blick“ / „hinter mir“ trennen Detail-Effekte von Raumlicht.
- Eigene Effekte als Python/numpy-Shader (laufen in einem eigenen Prozess), **Looks** als
  wiederverwendbare Clip-Gruppen mit Zeiten in Beats (vier mitgeliefert, eigene aus jeder Auswahl).
- Starter-Show aus Instrumenten und Raum: jeder sichtbare Strip zeigt ein Instrument (Schlagzeug als kleine
  Treffer, Gesang/Lead und Bass als Noten), Cues auf Drops, Build-ups, Fills und Crashes, leise Passagen fast
  dunkel; die Prüfung warnt vor zu heller Show, hellen leisen Stellen, fehlendem Kontrast und Stillstand.
- 3D-Vorschau mit Bloom und Betrachter-Sicht; alle Bereiche lassen sich an den Trennlinien größer/kleiner ziehen.
- **Export** als FSEQ-v2-Paket für xLights / Falcon Player (kalibrierte Werte, Audio, Kanal-Zuordnung).

**KI**
- *Show mit KI erstellen*: nutzt dein lokal installiertes **Claude Code** im Hintergrund (`claude -p`) mit deinem
  Claude-Abo – keine API-Kosten. Claude bekommt nur die Werkzeuge dieser App (kein Datei- oder Shell-Zugriff).
- MCP-Server unter `/mcp` für eigene KI-Clients (Claude Desktop, Claude Code, …).

## Voraussetzungen

- Python ≥ 3.12 (getestet mit 3.14; zstd-komprimierter Export braucht 3.14)
- Node.js ≥ 20 (zum Bauen der Oberfläche)
- Optional: [Claude Code](https://claude.com/claude-code), angemeldet mit deinem Claude-Konto, für die eingebaute KI

## Installation und Start

```powershell
.\start.ps1                # richtet beim ersten Start alles ein, öffnet http://127.0.0.1:8000
.\create_shortcut.ps1      # optional: Desktop-Verknüpfung, App läuft im eigenen Fenster
```

Manuell:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
cd ..\frontend
npm install
npm run build
..\backend\.venv\Scripts\lsg            # Server im Terminal
..\backend\.venv\Scripts\lsg-desktop    # oder als App-Fenster (schließen = beenden)
```

Entwicklung mit Hot-Reload: Backend starten und zusätzlich `npm run dev` in `frontend` (<http://localhost:5173>).

### Umgebungsvariablen

| Variable       | Standard    | Bedeutung                                                     |
|----------------|-------------|---------------------------------------------------------------|
| `LSG_DATA`     | `./data`    | Projekte, Songs, Shows, Einstellungen                         |
| `LSG_PORT`     | `8000`      | HTTP-Port                                                     |
| `LSG_HOST`     | `127.0.0.1` | Bind-Adresse                                                  |
| `LSG_AUDIO`    | `device`    | `null` = stumme Uhr ohne Soundkarte (Tests, Server)          |
| `LSG_FPS`      | `50`        | höchste Bildrate für DDP (langsamere Controller bekommen weniger) |
| `LSG_STEMS`    | `auto`      | Instrumententrennung: `auto`, `demucs`, `approx` (schnell, ohne Gesang), `off` |

## Erste Schritte mit echten LEDs

1. WLED: LED-Typ, Anzahl und Farbreihenfolge einstellen; *Receive UDP realtime* aktiv lassen (DDP, UDP 4048).
2. App → *Controller*: Gerät suchen oder IP eingeben, Strips zuordnen, mit *Test* Anfang (grün) und Ende (rot)
   prüfen, Strombudget des Netzteils eintragen.
3. *Kalibrierung* im abgedunkelten Raum: Mindeststufe finden, Kurve prüfen, dunkle Stufen und Weißabgleich.
4. *Kalibrierung → Synchronisation*: Sync-Test starten und Audio-Latenz einstellen, bis Klick und Blitz zusammenfallen.
5. Song hochladen, Show erstellen (Starter, Editor oder KI), im Player auf **LIVE** schalten.

Mehr FPS bei langen Strips: In WLED die LEDs auf mehrere Ausgänge (Datenpins) verteilen – die Pins werden
parallel beschrieben, z. B. 2 × 437 statt 1 × 873 LEDs ≈ 50 statt 32 FPS. WLAN-Energiesparen in WLED ausschalten.

Ohne Hardware testen: `backend\.venv\Scripts\lsg-wled-sim --leds 600 --http 8081 [--pins 2]` startet einen
simulierten WLED-Controller (per mDNS auffindbar, empfängt DDP, zeigt wie ein echter höchstens so viele Bilder,
wie seine Pins schaffen; `/sim/stats` meldet empfangene und angezeigte FPS).

## KI

**In der App** (*Shows → Mit KI*): Song wählen, Wunsch beschreiben, *Show generieren*. Der Fortschritt erscheint
live; das Ergebnis ist eine normale, bearbeitbare Show mit Versionsverlauf. Die Verbindungsdaten für eigene
KI-Programme zeigt der Knopf *MCP* oben rechts.

**Eigener Client:** MCP-Endpunkt `http://127.0.0.1:8000/mcp`
- Claude Code: `claude mcp add --transport http lightshow http://127.0.0.1:8000/mcp`
- Claude Desktop (`claude_desktop_config.json`):
  `{ "mcpServers": { "lightshow": { "command": "npx", "args": ["-y", "mcp-remote", "http://127.0.0.1:8000/mcp"] } } }`

Die KI bekommt die Instrumentenspuren (wer trägt welchen Abschnitt, Drops, Build-ups, Fills, Noten) und darf den
Song kurz im Internet recherchieren.

Werkzeuge: `get_overview`, `get_song_analysis`, `get_song_events`, `get_led_positions`, `list_effects`, `get_show_format`,
`create_show`, `add_clips`, `update_clips`, `remove_clips`, `update_show`, `delete_show`, `validate`,
`analyze_light`, `analyze_power`, `list_looks`, `apply_look`, `list_show_versions`, `restore_show_version`, `write_shader`,
`get_shader`, `get_shader_api`, `render_snapshot`, `render_timeline`, `preview`, `playback`.

## Show-Format (Kurzfassung)

```json
{
  "name": "Party", "song_id": "…",
  "layers": [
    { "name": "Raum", "clips": [
      { "start": 0, "end": 48, "effect": "noise", "params": { "palette": "ocean", "brightness": 0.08 },
        "target": { "view": "indirect" } } ] },
    { "name": "Drums", "clips": [
      { "start": 16.5, "end": 48, "effect": "hits", "blend": "max",
        "params": { "trigger": "kick", "palette": ["#40c0ff", "#ffffff"], "count": 3, "size": 12, "decay": 0.2 },
        "target": { "tags": ["wall"], "view": "direct" } } ] }
  ]
}
```

Helligkeiten sind wahrgenommen: Grundstimmung 0,03–0,15, Akzente 0,6–1,0, nichts unter 0,03. Lange Strips
hellen den ganzen Raum auf und brauchen weniger. `"dynamics": 0.6` auf der Show dunkelt leise Passagen ab;
Trigger wie `"kick"`, `"vocal"`, `"drop"` oder `"once"` (einmaliger Cue zum Clip-Start). Die vollständige Beschreibung liefert `get_show_format`.

## Architektur

```
frontend/  React + Three.js (react-three-fiber)  ──REST/WebSocket──►  backend/ FastAPI (lsg)
backend/lsg/
  model/      Raum, Fixtures, Controller, Kalibrierung, Betrachter, Songs, Shows
  geometry/   Fixture → LED-Positionen, betrachterbezogene Koordinaten
  audio/      Analyse (librosa, beat_this), Instrumententrennung (Demucs) und -spuren, Live-Analyse, Bibliothek,
              Player, Demo-Songs
  render/     Effekte, Parameter, Shader (+ Worker-Prozess), Looks, Engine, Validierung, Snapshots
  output/     Kalibrierkurve, Ausgabe-Pipeline mit Strombegrenzung, DDP, WLED-API/mDNS, FSEQ-Export
  playback/   Takt-Schleife, Testmuster, Sync-Test, Live-Eingang
  storage/    Projekte, Shows, Looks, Versionsverlauf
  ai_agent    Claude-Code-Anbindung      mcp_server   MCP-Werkzeuge      desktop   App-Fenster
```

Eine einzige Render-Engine erzeugt Vorschau, Live-Ausgabe, Export und KI-Snapshots – alle zeigen dasselbe.

## Tests und Qualität

```powershell
cd backend
.venv\Scripts\python -m pytest            # ~125 Unit- und Integrationstests
.venv\Scripts\python -m pytest -m ml      # mit den neuronalen Modellen (Demucs)
.venv\Scripts\python -m pytest -m ui      # Browser-Ende-zu-Ende-Test (braucht gebautes Frontend + Playwright)
.venv\Scripts\python -m ruff check lsg tests
cd ..\frontend; npm run lint; npm run typecheck
```

GitHub Actions (`.github/workflows/ci.yml`) führt Backend-Tests (Python 3.12/3.14), Lint, Typecheck, Build und den
Browser-Test aus.

## Hinweise

- Shader laufen in einem eigenen Prozess und mit eingeschränktem Python; das schützt vor Hängern und Versehen,
  ist aber keine Sicherheitsgrenze gegen absichtlich bösartigen Code.
- Abschnittsnamen sind heuristisch; die Ähnlichkeits-Labels (A, B, C …) zeigen, welche Teile gleich klingen.
- Der MCP-Server ist nur lokal erreichbar (DNS-Rebinding-Schutz für localhost).
