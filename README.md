# Neopixel Light Show Generator

Musiksynchrone Lichtshows für adressierbare LEDs (WS2812B, SK6812 RGB/RGBW) an WLED-Controllern –
mit 3D-Raummodell, Betrachterposition, Songanalyse und einem MCP-Server, über den eine KI Shows programmiert.

## Funktionen

- **Raum**: Grundriss als 2D-Skizze zeichnen (Ecken ziehen, einfügen, löschen, Vorlagen) plus Raumhöhe.
- **LED-Strips**: Linien, Bezier-Kurven, Bögen, Kreise und Matrizen im Raum platzieren; Presets wie
  Deckenumrandung, Wandleiste, Eckstreifen, Deckenring, Wand-Matrix; Punkte per 3D-Gizmo verschieben
  (rastet an Wänden, Boden und Decke ein); LED-Dichte bzw. feste Anzahl, Datenrichtung, Tags.
- **Betrachter**: Position und Blickrichtung. Jede LED kennt ihren Winkel links/rechts, ihre Höhe im
  Blickfeld und ihre Entfernung – Effekte können sich darauf beziehen („Welle von links nach rechts").
- **Controller**: WLED-Geräte per mDNS finden oder per IP hinzufügen, Strips auf Pixelbereiche
  zuordnen, Testmuster (Anfang grün, Ende rot), Live-Ausgabe per DDP mit ~50 FPS, Latenz je Controller,
  Gamma, Helligkeit, Audio-Latenz.
- **Songs**: mp3/wav/flac/ogg hochladen; automatische Analyse von Tempo, Beats, Takten, Abschnitten
  (Intro/Strophe/Refrain/Break/Bridge/Outro) und Lautstärke je Frequenzband; Tempo-Korrektur ×2/÷2.
- **Shows**: Ebenen mit Effekt-Clips (14 Effekte, Audio-Bindings, Keyframes, beat-synchrone LFOs,
  räumliche Ziele) plus eigene Python/numpy-Shader. Starter-Show aus der Songstruktur, 3D-Vorschau mit
  Bloom, Betrachter-Sicht, Timeline, JSON-Editor, Prüfung.
- **KI/MCP**: Streamable-HTTP-MCP-Server unter `/mcp` – die KI liest Raum, LEDs, Betrachter und
  Musikanalyse, schreibt Shows und Shader und prüft ihr Ergebnis über gerenderte Bilder.

## Voraussetzungen

- Python ≥ 3.12 (getestet mit 3.14)
- Node.js ≥ 20 (nur zum Bauen der Oberfläche)

## Installation

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"

cd ..\frontend
npm install
npm run build
```

## Starten

```powershell
.\start.ps1          # oder: backend\.venv\Scripts\lsg
```

Dann <http://127.0.0.1:8000> öffnen. Die Musik wird über die Soundkarte des PCs abgespielt; ihre
Position ist der Taktgeber für Vorschau und LEDs.

Entwicklung mit Hot-Reload der Oberfläche: Backend starten und zusätzlich `npm run dev` im Ordner
`frontend` (<http://localhost:5173>, leitet `/api`, `/ws` und `/mcp` an Port 8000 weiter).

### Umgebungsvariablen

| Variable       | Standard          | Bedeutung                                               |
|----------------|-------------------|---------------------------------------------------------|
| `LSG_DATA`     | `./data`          | Projekte, Songs, Shows                                   |
| `LSG_PORT`     | `8000`            | HTTP-Port                                               |
| `LSG_HOST`     | `127.0.0.1`       | Bind-Adresse                                            |
| `LSG_AUDIO`    | `device`          | `null` = stumme Uhr ohne Soundkarte (Tests, Server)    |
| `LSG_FPS`      | `50`              | Bildrate für Rendering und DDP                          |

## WLED einrichten

1. In WLED unter *LED Preferences* LED-Typ (WS2812B / SK6812 / SK6812 RGBW), Anzahl und Farbreihenfolge
   einstellen. Die Anzahl muss alle in der App zugeordneten Pixel abdecken.
2. Unter *Sync Interfaces* muss *Receive UDP realtime* aktiv sein (Standard). DDP läuft auf UDP-Port 4048.
3. In der App unter *Controller* das Gerät hinzufügen, Strips zuordnen und mit *Test* prüfen, ob Anfang
   (grün) und Ende (rot) stimmen – sonst *Datenrichtung umgekehrt* setzen.
4. Im Player auf **LIVE** schalten. Nach Ende der Show kehrt WLED nach ca. 2,5 s zum eigenen Effekt zurück.

Wirken die Farben zu blass oder zu dunkel, Gamma unter *Controller → Ausgabe* anpassen
(1.0, falls WLED bereits selbst eine Gammakorrektur anwendet).

Ohne Hardware testen: `backend\.venv\Scripts\lsg-wled-sim --leds 600 --http 8081` startet einen
simulierten WLED-Controller (per mDNS auffindbar, empfängt DDP, `/sim/stats` zeigt die FPS).

## KI-Shows (MCP)

Endpunkt: `http://127.0.0.1:8000/mcp` (die App muss laufen).

- **Claude Code**: `claude mcp add --transport http lightshow http://127.0.0.1:8000/mcp`
- **Claude Desktop** (`claude_desktop_config.json`):
  ```json
  { "mcpServers": { "lightshow": { "command": "npx", "args": ["-y", "mcp-remote", "http://127.0.0.1:8000/mcp"] } } }
  ```

Werkzeuge: `get_overview`, `get_song_analysis`, `get_led_positions`, `list_effects`, `get_show_format`,
`create_show`, `add_clips`, `update_clips`, `remove_clips`, `update_show`, `delete_show`, `validate`,
`write_shader`, `get_shader`, `get_shader_api`, `render_snapshot`, `render_timeline`, `preview`, `playback`.

## Show-Format (Kurzfassung)

```json
{
  "name": "Party", "song_id": "…",
  "layers": [
    { "name": "Base", "clips": [
      { "start": 0, "end": 16.5, "effect": "noise", "params": { "palette": "ocean", "brightness": 0.5 } } ] },
    { "name": "Beat", "clips": [
      { "start": 16.5, "end": 48, "effect": "pulse", "blend": "add",
        "params": { "color": "#ff0080", "trigger": "beat", "decay": 0.15 },
        "target": { "tags": ["ceiling"] } },
      { "start": 16.5, "end": 48, "effect": "wave", "blend": "add",
        "params": { "axis": "azimuth", "beats": 2, "brightness": { "audio": "low", "min": 0.2, "max": 1 } } } ] }
  ]
}
```

Effekte: `solid`, `gradient`, `rainbow`, `pulse`, `strobe`, `chase`, `wave`, `ripple`, `sparkle`, `fade`,
`vu`, `noise`, `spotlight`, `split` sowie `shader:<name>`. Die vollständige Beschreibung liefert das
MCP-Werkzeug `get_show_format` bzw. die Seite *KI / MCP*.

## Architektur

```
frontend/  React + Three.js (react-three-fiber)  ──REST/WebSocket──►  backend/ FastAPI
backend/lsg/
  model/      Raum, Fixtures, Controller, Betrachter, Songs, Shows (pydantic)
  geometry/   Fixture → LED-Positionen, betrachterbezogene Koordinaten
  audio/      Analyse (librosa), Bibliothek, Player (Audio-Uhr), Demo-Songs
  render/     Effekte, Parameter, Shader-Sandbox, Engine, Validierung, Snapshots
  output/     DDP, Pixel-Zuordnung, WLED-API, mDNS
  playback/   Takt-Schleife: rendern → Browser-Vorschau + WLED
  mcp_server  MCP-Werkzeuge
```

Eine einzige Render-Engine erzeugt die Bilder für Vorschau, Live-Ausgabe und KI-Snapshots – alle drei
zeigen immer dasselbe.

## Tests

```powershell
cd backend
.venv\Scripts\python -m pytest
```

Die Tests decken Geometrie, Audioanalyse, Effekte, Shader-Sandbox, DDP, REST-API, Live-Ausgabe an einen
simulierten WLED-Controller und den MCP-Server Ende-zu-Ende ab.

## Hinweise

- Shader laufen mit eingeschränktem Python (nur numpy/math, keine Importe, keine `while`-Schleifen). Das
  verhindert Versehen, ist aber keine Sicherheitsgrenze gegen absichtlich bösartigen Code.
- Der MCP-Server ist nur lokal erreichbar (DNS-Rebinding-Schutz für localhost).
- Abschnittsnamen sind heuristisch; die Ähnlichkeits-Labels (A, B, C …) zeigen, welche Teile gleich klingen.
