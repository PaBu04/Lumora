/**
 * Help texts: the (?) tips next to terms and the in-app manual use the same entries.
 * Bodies are short paragraphs separated by blank lines; "- " starts a list item.
 */

export interface HelpEntry {
  chapter: string;
  title: { de: string; en: string };
  body: { de: string; en: string };
}

export const CHAPTERS: Record<string, { de: string; en: string }> = {
  start: { de: "Erste Schritte", en: "Getting started" },
  room: { de: "Raum und LED-Strips", en: "Room and LED strips" },
  devices: { de: "Controller", en: "Controllers" },
  calibration: { de: "Kalibrierung", en: "Calibration" },
  songs: { de: "Songs und Analyse", en: "Songs and analysis" },
  shows: { de: "Shows und Effekte", en: "Shows and effects" },
  ai: { de: "KI", en: "AI" },
  safety: { de: "Sicherheit", en: "Safety" },
};

export const HELP: Record<string, HelpEntry> = {
  firstshow: {
    chapter: "start",
    title: { de: "Deine erste Show in sechs Schritten", en: "Your first show in six steps" },
    body: {
      de: `- Raum: Grundriss zeichnen (oder eine Vorlage nehmen) und die Raumhöhe eintragen. Setz den Betrachter dorthin, wo du sitzt.
- LED-Strips: Strips so einzeichnen, wie sie im Raum hängen – Linien, Bögen, Kreise oder Matrizen. Die Vorlagen helfen.
- Controller: deinen WLED-Controller suchen und die Strips seinen Pixeln zuordnen. Ohne Hardware kannst du diesen Schritt überspringen und alles in der 3D-Vorschau ansehen.
- Songs: eine Audiodatei hochladen. Die Analyse erkennt Takt, Abschnitte, Instrumente, Akkorde und Motive (etwa eine Minute).
- Shows: „+ Neue Show“ mit einem Stil erstellen – die Starter-Show folgt der Musik. Oder „Mit KI“ eine Show beschreiben.
- Abspielen: in der Vorschau ansehen, oben rechts auf „Live“ schalten, damit die LEDs mitspielen.`,
      en: `- Room: draw the floor plan (or use a template) and enter the room height. Place the viewer where you sit.
- LED strips: draw the strips as they hang in the room – lines, arcs, circles or matrices. The presets help.
- Controllers: find your WLED controller and map the strips to its pixels. Without hardware you can skip this step and watch everything in the 3D preview.
- Songs: upload an audio file. The analysis finds the beat, sections, instruments, chords and motifs (about a minute).
- Shows: "+ New show" with a style – the starter show follows the music. Or describe a show "With AI".
- Play: watch it in the preview, switch to "Live" (top right) so the LEDs play along.`,
    },
  },
  preview_live: {
    chapter: "start",
    title: { de: "Vorschau und Live", en: "Preview and live" },
    body: {
      de: "In der Vorschau siehst du die Show nur in der 3D-Ansicht. „Live“ schickt jedes Bild zusätzlich an die WLED-Controller (per DDP). Der Schalter gilt für die ganze App, auch für Testmuster der Kalibrierung.",
      en: 'In preview the show only plays in the 3D view. "Live" also sends every frame to the WLED controllers (via DDP). The switch applies to the whole app, including calibration test patterns.',
    },
  },
  room: {
    chapter: "room",
    title: { de: "Raum und Grundriss", en: "Room and floor plan" },
    body: {
      de: "Der Grundriss ist ein Vieleck in Metern. Ecken ziehen, auf eine Wand klicken fügt eine Ecke ein, Doppelklick löscht sie. Du kannst ein Foto oder einen Bauplan hochladen, den Maßstab über zwei Punkte festlegen und die Ecken nachklicken. Die Raumhöhe brauchst du für Strips an der Decke.",
      en: "The floor plan is a polygon in metres. Drag corners, click a wall to add a corner, double-click to delete one. You can upload a photo or blueprint, set the scale with two points and click along the corners. The room height matters for strips on the ceiling.",
    },
  },
  viewer: {
    chapter: "room",
    title: { de: "Betrachter", en: "Viewer" },
    body: {
      de: "Der Betrachter ist dein Platz im Raum und deine Blickrichtung. Daraus weiß die App, welche LEDs du direkt siehst (vor dir) und welche nur indirekt als Licht an Wand und Decke (hinter oder neben dir). Effekte wie „von links nach rechts durchs Blickfeld“ richten sich danach.",
      en: 'The viewer is your seat in the room and the direction you look. From it the app knows which LEDs you see directly (in front of you) and which only indirectly as light on walls and ceiling (behind or beside you). Effects like "left to right across your view" follow it.',
    },
  },
  strips: {
    chapter: "room",
    title: { de: "LED-Strips", en: "LED strips" },
    body: {
      de: "Ein Strip ist eine Form im Raum mit einer Anzahl LEDs: Linie über mehrere Punkte, Bezier-Kurve, Bogen, Kreis oder Matrix. Die Reihenfolge der Punkte ist die Datenrichtung – die erste LED sitzt am ersten Punkt. Gib entweder LEDs pro Meter oder die genaue Anzahl an. LED-Typ (WS2812B, SK6812 RGB/RGBW) wählen, damit Farben und Strom stimmen.",
      en: "A strip is a shape in the room with a number of LEDs: a line through several points, a Bezier curve, an arc, a circle or a matrix. The order of the points is the data direction – the first LED sits at the first point. Enter LEDs per metre or the exact count. Choose the LED type (WS2812B, SK6812 RGB/RGBW) so colours and current are right.",
    },
  },
  controller: {
    chapter: "devices",
    title: { de: "WLED-Controller verbinden", en: "Connecting WLED controllers" },
    body: {
      de: `Die App findet WLED-Geräte im selben Netzwerk automatisch (mDNS) – oder du gibst die IP-Adresse ein. Sie sendet die Bilder per DDP (UDP-Port 4048).
- In WLED muss „Receive UDP realtime“ aktiv sein (Standard).
- LED-Typ, Anzahl und Farbreihenfolge stellst du in WLED ein; die App liest sie aus.
- Ist ein Gerät „nicht erreichbar“: gleiches WLAN? IP-Adresse noch aktuell? WLAN-Energiesparen in WLED ausschalten.`,
      en: `The app finds WLED devices on the same network automatically (mDNS) – or you enter the IP address. It sends frames via DDP (UDP port 4048).
- "Receive UDP realtime" must be on in WLED (default).
- Set LED type, count and colour order in WLED; the app reads them.
- If a device is "unreachable": same Wi-Fi? IP address still right? Turn off Wi-Fi sleep in WLED.`,
    },
  },
  mapping: {
    chapter: "devices",
    title: { de: "Strips zuordnen", en: "Mapping strips" },
    body: {
      de: "Jeder Strip bekommt einen Bereich der Pixel eines Controllers: ab welcher LED-Nummer, wie viele und ob umgedreht. Mit „Test“ leuchtet der Anfang grün und das Ende rot – so siehst du sofort, ob Richtung und Bereich stimmen.",
      en: 'Each strip gets a range of a controller\'s pixels: starting LED number, count and whether it is reversed. "Test" lights the start green and the end red, so you see at once whether direction and range are right.',
    },
  },
  fps: {
    chapter: "devices",
    title: { de: "Bildrate pro Controller", en: "Frame rate per controller" },
    body: {
      de: "Ein WLED kann nur so viele Bilder zeigen, wie seine Datenleitungen schaffen: WS2812B brauchen etwa 30 µs pro LED und Pin, 873 LEDs an einem Pin ergeben gut 30 Bilder pro Sekunde. Die App schickt jedem Controller knapp unter seinem Maximum. „Geschwindigkeit messen“ ermittelt die echte Rate; mehr Datenpins erhöhen sie.",
      en: 'A WLED can only show as many frames as its data lines allow: WS2812B need about 30 µs per LED and pin, so 873 LEDs on one pin give about 30 frames per second. The app sends each controller just below its maximum. "Measure speed" finds the real rate; more data pins raise it.',
    },
  },
  power: {
    chapter: "devices",
    title: { de: "Strombudget", en: "Power budget" },
    body: {
      de: "Trag ein, wie viel Strom das Netzteil eines Controllers liefert. Die App schätzt den Strom jedes Bildes und dimmt automatisch, bevor das Budget überschritten wird. Die Prüfung einer Show zeigt den Stromverlauf.",
      en: "Enter how much current a controller's power supply delivers. The app estimates the current of every frame and dims automatically before the budget is exceeded. A show's check shows the current over time.",
    },
  },
  calibration: {
    chapter: "calibration",
    title: { de: "Warum kalibrieren?", en: "Why calibrate?" },
    body: {
      de: "LEDs werden nicht gleichmäßig heller: zwischen den Stufen 1, 2 und 3 liegen große Sprünge, 254 und 255 sehen gleich aus. Shows rechnen deshalb in wahrgenommener Helligkeit (0,5 sieht halb so hell aus); die Kalibrierung setzt sie in PWM-Werte für deine LEDs um. Einmal pro LED-Typ, am besten im abgedunkelten Raum.",
      en: "LEDs do not get brighter evenly: steps 1, 2 and 3 are big jumps, 254 and 255 look the same. Shows therefore work in perceived brightness (0.5 looks half as bright); calibration turns it into PWM values for your LEDs. Once per LED type, best in a darkened room.",
    },
  },
  min_level: {
    chapter: "calibration",
    title: { de: "Mindeststufe", en: "Minimum level" },
    body: {
      de: "Die kleinste Stufe, bei der eine LED sauber und farbtreu leuchtet. Darunter flackern viele LEDs oder zeigen falsche Farben. Dunkle Szenen beginnen bei dieser Stufe.",
      en: "The lowest level at which an LED lights cleanly and in the right colour. Below it many LEDs flicker or show wrong colours. Dark scenes start at this level.",
    },
  },
  curve: {
    chapter: "calibration",
    title: { de: "Helligkeitskurve", en: "Brightness curve" },
    body: {
      de: "CIE L* entspricht dem menschlichen Helligkeitsempfinden und passt für die meisten LEDs. Mit Gamma kannst du nachregeln: Wirken die hellen Stufen zu ähnlich, Gamma erhöhen; wirken die dunklen zu ähnlich, senken. „Maximum“ begrenzt die höchste PWM-Stufe.",
      en: 'CIE L* matches human brightness perception and suits most LEDs. With gamma you can fine-tune: if the bright steps look too alike, raise gamma; if the dark ones do, lower it. "Maximum" caps the highest PWM level.',
    },
  },
  dithering: {
    chapter: "calibration",
    title: { de: "Dithering", en: "Dithering" },
    body: {
      de: "Sehr dunkle Helligkeiten liegen zwischen zwei PWM-Stufen. Dithering verteilt den Zwischenwert: räumlich auf benachbarte LEDs (ruhig, empfohlen) oder zeitlich über mehrere Bilder (feiner, kann leicht flimmern). „Aus unterhalb“ schaltet ganz dunkle Werte komplett aus.",
      en: 'Very dark levels fall between two PWM steps. Dithering spreads the in-between value: spatially over neighbouring LEDs (calm, recommended) or temporally over several frames (finer, may flicker slightly). "Off below" switches very dark values off completely.',
    },
  },
  white_balance: {
    chapter: "calibration",
    title: { de: "Weißabgleich", en: "White balance" },
    body: {
      de: "Weiß soll neutral wirken – vergleiche mit einem weißen Blatt Papier. Den zu starken Farbkanal reduzieren. Bei RGBW-LEDs mischt „farbrichtig“ die weiße LED passend zu ihrer eigenen Farbe ein.",
      en: 'White should look neutral – compare with a white sheet of paper. Reduce the channel that is too strong. With RGBW LEDs, "colour-accurate" mixes in the white LED according to its own colour.',
    },
  },
  sync: {
    chapter: "calibration",
    title: { de: "Ton und Licht synchronisieren", en: "Syncing sound and light" },
    body: {
      de: "Lautsprecher (vor allem Bluetooth) und Controller haben Verzögerungen. Der Sync-Test spielt einen Klick auf jeden Beat und lässt alle LEDs mitblitzen. Stell dich an den Betrachterplatz und schieb die Audio-Latenz, bis Klick und Blitz zusammenfallen. Kommt das Licht zu früh, Audio-Latenz erhöhen.",
      en: "Speakers (Bluetooth above all) and controllers have delays. The sync test plays a click on every beat and flashes all LEDs with it. Stand at the viewer position and move the audio latency until click and flash coincide. If the light comes too early, raise the audio latency.",
    },
  },
  analysis: {
    chapter: "songs",
    title: { de: "Was die Analyse erkennt", en: "What the analysis finds" },
    body: {
      de: `- Tempo, Beats und Takte (auch 3/4).
- Instrumente: Der Song wird mit dem KI-Modell Demucs in Schlagzeug, Bass, Gesang und Rest getrennt. Daraus entstehen Spuren: Kick, Snare, Hi-Hat, Crash mit Anschlagstärke, Bass-, Gesangs- und Keys-Noten mit Tonhöhe, Fills, Build-ups und Drops.
- Harmonie: Tonart und Akkorde.
- Songform: Abschnitte mit Namen, Intensität und Höhepunkt; wiederkehrende Riffs (Motive).
Im Songs-Tab kannst du den Song abspielen und mitverfolgen, was erkannt wurde.`,
      en: `- Tempo, beats and bars (also 3/4).
- Instruments: the AI model Demucs separates the song into drums, bass, vocals and the rest. From these come tracks: kick, snare, hi-hat, crash with velocity, bass, vocal and keys notes with pitch, fills, build-ups and drops.
- Harmony: key and chords.
- Song form: named sections with intensity and the peak; recurring riffs (motifs).
In the Songs tab you can play the song and follow what was found.`,
    },
  },
  tempo: {
    chapter: "songs",
    title: { de: "Tempo korrigieren", en: "Correcting the tempo" },
    body: {
      de: "Liegt die Erkennung daneben, setzt du das Tempo von Hand: ÷2 und ×2 für doppelte oder halbe Geschwindigkeit, ±1 und ±0,1 BPM zum Feinjustieren. Die Beats werden dann als gleichmäßiges Raster neu gesetzt. Ein von Hand gesetztes Tempo bleibt bei einer neuen Analyse erhalten.",
      en: "If the detection is off, set the tempo by hand: ÷2 and ×2 for double or half speed, ±1 and ±0.1 BPM to fine-tune. The beats are then laid out as an even grid. A tempo set by hand is kept when the song is analysed again.",
    },
  },
  songform: {
    chapter: "songs",
    title: { de: "Songform: Abschnitte, Intensität, Höhepunkt", en: "Song form: sections, intensity, peak" },
    body: {
      de: "Die Abschnitte entstehen dort, wo sich die Besetzung ändert (Schlagzeug, Bass oder Gesang setzen ein oder aus), bevorzugt nach 4, 8 oder 16 Takten. Gleiche Buchstaben klingen gleich – Refrain 1 und Refrain 2 bekommen denselben. Die Intensität 1–5 ist relativ zum Song; der Höhepunkt (★) ist der stärkste Teil. Shows heben sich ihr hellstes Bild dafür auf.",
      en: "Sections start where the instrumentation changes (drums, bass or vocals come in or stop), preferably after 4, 8 or 16 bars. Equal letters sound alike – chorus 1 and chorus 2 get the same one. Intensity 1–5 is relative to the song; the peak (★) is its strongest part. Shows keep their brightest look for it.",
    },
  },
  harmony: {
    chapter: "songs",
    title: { de: "Tonart und Akkorde", en: "Key and chords" },
    body: {
      de: "Aus den erkannten Noten von Keys und Bass ermittelt die App die Tonart und die Akkorde Schlag für Schlag, mit ihrer Stufe (I = Grundton, V = Spannung zurück zur I). Moll-Tonarten bekommen in automatischen Farbwelten eher kühle, Dur-Tonarten eher warme Farben; Akkordwechsel sind gute Momente für Farbwechsel.",
      en: "From the detected keys and bass notes the app finds the key and the chords beat by beat, with their degree (I = home, V = tension back to I). In automatic colour worlds minor keys get cooler and major keys warmer colours; chord changes are good moments for colour changes.",
    },
  },
  motifs: {
    chapter: "songs",
    title: { de: "Motive", en: "Motifs" },
    body: {
      de: "Ein Motiv ist ein Riff oder eine Melodie, die mindestens dreimal wiederkommt – etwa das Klavier-Hook im Drop. Starter-Shows geben jedem Motiv eine eigene Licht-Geste, die jedes Mal kommt, wenn das Riff spielt. So wird die Musik sichtbar.",
      en: "A motif is a riff or melody that comes back at least three times – like the piano hook in the drop. Starter shows give each motif its own light gesture that comes every time the riff plays. That makes the music visible.",
    },
  },
  stems: {
    chapter: "songs",
    title: { de: "Instrumente getrennt oder geschätzt", en: "Instruments separated or estimated" },
    body: {
      de: "Mit installiertem PyTorch trennt das Modell Hybrid Demucs den Song in Schlagzeug, Bass, Gesang und Rest (~1 Minute pro Song). Ohne PyTorch werden Schlagzeug, Bass und Rest aus dem Klang geschätzt – Gesang fehlt dann.",
      en: "With PyTorch installed, the Hybrid Demucs model separates the song into drums, bass, vocals and the rest (~1 minute per song). Without PyTorch, drums, bass and the rest are estimated from the sound – vocals are missing then.",
    },
  },
  show: {
    chapter: "shows",
    title: { de: "Shows, Ebenen und Clips", en: "Shows, layers and clips" },
    body: {
      de: "Eine Show gehört zu einem Song und besteht aus Ebenen voller Clips. Ein Clip spielt einen Effekt von–bis auf einem Ziel (Strips oder ein Bereich des Raums). Obere Ebenen liegen über unteren; der Mischmodus bestimmt, wie sie sich verbinden. Clips rasten an Beats, Takten und an Momenten der Musik ein.",
      en: "A show belongs to a song and consists of layers full of clips. A clip plays an effect from–to on a target (strips or an area of the room). Upper layers lie on top of lower ones; the blend mode decides how they combine. Clips snap to beats, bars and moments of the music.",
    },
  },
  styles: {
    chapter: "shows",
    title: { de: "Starter-Show und Stile", en: "Starter show and styles" },
    body: {
      de: `Die Starter-Show entsteht aus der Analyse und deinem Raum: Schlagzeug als kleine Treffer, Melodie und Bass als Noten, Cues auf Drops, Build-ups und Fills, leise Stellen dunkel, der Höhepunkt am hellsten.
- Party: viel Schlagzeug und Akzente.
- Ruhig: weiche Übergänge, die Raumfarbe folgt den Akkorden.
- Kino: großer Bogen, Gesten auf Phrasen und Motiven, starker Kontrast.
- Minimal: nur Schlagzeug und Melodie.
Rechtsklick auf eine Show → „Neue Variante würfeln“ erzeugt eine andere Fassung im selben Stil.`,
      en: `The starter show is built from the analysis and your room: drums as small hits, melody and bass as notes, cues on drops, build-ups and fills, quiet parts dark, the peak brightest.
- Party: lots of drums and accents.
- Calm: soft transitions, the room colour follows the chords.
- Cinematic: a big arc, gestures on phrases and motifs, strong contrast.
- Minimal: only drums and melody.
Right-click a show → "Roll a new variant" creates another version in the same style.`,
    },
  },
  triggers: {
    chapter: "shows",
    title: { de: "Auslöser", en: "Triggers" },
    body: {
      de: "Effekte wie Pulse, Hits, Sweep oder Ripple feuern auf einen Auslöser: das Beat-Raster (Beat, Takt), Anschläge oder eine Instrumentenspur (Kick, Snare, Hi-Hat, Bass, Gesang, Keys, Melodie, Akkord, Stab, Fill, Drop, Motiv …). „Einmal“ feuert genau einmal am Clip-Anfang – ein Cue. „Anschlagstärke“ macht leise Schläge dunkler, „Halten“ lässt das Licht an, solange der Ton klingt.",
      en: 'Effects like pulse, hits, sweep or ripple fire on a trigger: the beat grid (beat, bar), onsets or an instrument track (kick, snare, hi-hat, bass, vocals, keys, melody, chord, stab, fill, drop, motif …). "Once" fires exactly once at the clip start – a cue. "Velocity" makes quiet hits darker, "sustain" keeps the light on while the note sounds.',
    },
  },
  target: {
    chapter: "shows",
    title: { de: "Ziel eines Clips", en: "A clip's target" },
    body: {
      de: "Ein Clip wirkt auf alle LEDs, auf ausgewählte Strips oder auf einen Bereich: „direkt“ sind die LEDs vor dem Betrachter, „indirekt“ die hinter oder neben ihm, die nur als Licht im Raum wirken. Details gehören auf direkte LEDs, Raumfarbe und große Blitze auf indirekte.",
      en: 'A clip affects all LEDs, selected strips or an area: "direct" are the LEDs in front of the viewer, "indirect" those behind or beside them, which only show as light in the room. Details belong on direct LEDs, room colour and big flashes on indirect ones.',
    },
  },
  blend: {
    chapter: "shows",
    title: { de: "Mischmodus", en: "Blend mode" },
    body: {
      de: "Wie ein Clip mit den Ebenen darunter zusammenkommt: Normal deckt ab, Addieren legt Licht dazu (für Blitze), Maximum nimmt das Hellere, Multiplizieren färbt ein oder dunkelt ab, Subtrahieren zieht Licht ab.",
      en: "How a clip combines with the layers below: normal covers, add puts light on top (for flashes), max takes the brighter one, multiply tints or darkens, subtract removes light.",
    },
  },
  dynamics: {
    chapter: "shows",
    title: { de: "Dynamik", en: "Dynamics" },
    body: {
      de: "Leise Stellen des Songs dunkeln die ganze Show ab, laute bleiben hell. 50–80 % geben einen deutlichen Unterschied zwischen dunklen und hellen Passagen – das macht eine Show spannend.",
      en: "Quiet passages of the song darken the whole show, loud ones stay bright. 50–80 % give a clear difference between dark and bright passages – that is what makes a show exciting.",
    },
  },
  cues: {
    chapter: "shows",
    title: { de: "Cues einspielen", en: "Playing in cues" },
    body: {
      de: "Während der Song läuft, setzt du mit den Tasten 1–7 (oder per Klick) einzelne Effekte: Blitz, Raumblitz, Ring, Wischer, Funkeln, Rise bis zum nächsten Drop. Sie rasten auf den nächsten Schlag ein und landen in der Ebene „Cues“.",
      en: "While the song plays, keys 1–7 (or a click) set single effects: flash, room flash, ring, wipe, sparkle, rise to the next drop. They snap to the nearest hit and land in the layer \"Cues\".",
    },
  },
  export: {
    chapter: "shows",
    title: { de: "Exportieren", en: "Exporting" },
    body: {
      de: "Der Export erzeugt eine FSEQ-Datei mit Audio und Kanalplan für xLights oder den Falcon Player – dann läuft die Show ohne PC, direkt auf einem Player im Netzwerk.",
      en: "The export creates an FSEQ file with audio and a channel map for xLights or the Falcon Player – the show then runs without a PC, on a player in the network.",
    },
  },
  ai: {
    chapter: "ai",
    title: { de: "Shows mit KI", en: "Shows with AI" },
    body: {
      de: "„Mit KI“ beschreibst du, wie die Show wirken soll. Die App startet dein lokales Claude Code (Standard: Opus 5.5) mit deinem Claude-Abo – ohne API-Kosten. Claude bekommt nur die Werkzeuge dieser App: Analyse lesen, Shows schreiben, Bilder der Show ansehen und prüfen. Ist Claude Code noch nicht eingerichtet, zeigt der Dialog eine Schritt-für-Schritt-Anleitung.",
      en: '"With AI" you describe how the show should feel. The app starts your local Claude Code (default: Opus 5.5) with your Claude subscription – no API costs. Claude only gets this app\'s tools: read the analysis, write shows, look at and check images of the show. If Claude Code is not set up yet, the dialog shows a step-by-step guide.',
    },
  },
  flash_limit: {
    chapter: "safety",
    title: { de: "Blitzbegrenzung", en: "Flash limit" },
    body: {
      de: "Lichtblitze können bei Menschen mit lichtempfindlicher Epilepsie Anfälle auslösen. Die App begrenzt große Blitze über den ganzen Raum auf höchstens drei pro Sekunde (einstellbar) und lässt Stroboskope nie schneller laufen. Frag Gäste vorher und brich eine Show ab, wenn jemand Beschwerden bemerkt.",
      en: "Flashes can trigger seizures in people with photosensitive epilepsy. The app limits large flashes over the whole room to at most three per second (adjustable) and never lets strobes run faster. Ask guests beforehand and stop a show if anyone feels unwell.",
    },
  },
};

export const SHORTCUTS: { keys: string; de: string; en: string }[] = [
  { keys: "Leertaste / Space", de: "Abspielen / Pause (Shows und Songs)", en: "Play / pause (shows and songs)" },
  { keys: "Strg+Z / Strg+Y", de: "Rückgängig / Wiederholen", en: "Undo / redo" },
  { keys: "1 – 7", de: "Cue einspielen (Shows)", en: "Play in a cue (shows)" },
  { keys: "Strg+C / Strg+V / Strg+D", de: "Clips kopieren / einfügen / duplizieren", en: "Copy / paste / duplicate clips" },
  { keys: "Entf", de: "Ausgewählte Clips löschen", en: "Delete selected clips" },
  { keys: "← / →", de: "Clips um einen Beat verschieben (mit Shift: einen Takt)", en: "Move clips by a beat (with Shift: a bar)" },
  { keys: "Strg+A", de: "Alle Clips auswählen", en: "Select all clips" },
  { keys: "Esc", de: "Auswahl aufheben, Dialog schließen", en: "Clear selection, close dialog" },
  { keys: "?", de: "Diese Übersicht", en: "This overview" },
];
