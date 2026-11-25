---
name: lynx-remote-control
description: >
  Arbeitsweise für das lynx-mcp MCP-Server-Werkzeugset (lynx_*) zur Steuerung
  einer laufenden LYNX-SHARE-Instanz über das lynx-control/1-Protokoll.
  WHEN: LYNX-Projekt lesen/ändern, Patterns/Notes/Mixer/Playlist bearbeiten,
  Tempo oder Transport setzen, Undo/Redo, "spiel das ab", "mach Pattern X …".
---

# LYNX Remote Control bedienen

Der MCP-Server `lynx-mcp` spiegelt die lokale API einer laufenden
LYNX-Instanz. Alle Regeln des Protokolls sind bereits in den
Tool-Beschreibungen; dieses Skill ergänzt die **Choreographie** über
mehrere Tools hinweg.

## Goldene Regeln

1. **Erst lesen, dann schreiben.** Jeder Write braucht einen frischen
   Projektzustand (`lynx_status` oder `lynx_read scope=summary`). Das
   Fence-Tripel setzt der Server selbst — nie `expected*`-Felder erfinden.
2. **Ein akzeptierter Schreibschritt = genau ein natives Undo.** Kein
   Auto-Rollback einbauen; zum Zurücktreten `lynx_history action=undo`.
3. **Fehler `changed`:** das Projekt hat sich (auch per UI) bewegt — Zustand
   neu lesen und Plan neu auflegen, nicht denselben Call wiederholen.
4. **Fehler `uncertain`:** Leitung nach möglichem Write abgebrochen.
   **Niemals automatisch wiederholen** — erst `lynx_status`/Read, dann
   entscheiden.
5. **Writes verlangen gestopptes Playback** (`lynx_transport action=stop`;
   `stop` funktioniert auch bei veraltetem Fence).
6. **Indizes sind flüchtig.** Nach Struktur-Änderungen (Channel/Pattern
   anlegen, Effekt laden) stammen alle Indizes aus dem letzten Read —
   `lynx_session` liefert sie neu.

## Rezept 1 — Standardzyklus für eine kleine Änderung

Beispiel „Mach Channel 2 leiser und das Tempo 140":

```
lynx_session                          # Index + aktuellen Zustand prüfen
lynx_transport action=stop            # falls läuft
lynx_channel_set index=1 volume=0.6   # (Indizes sind 0-basiert!)
lynx_tempo_set bpm=140.0
lynx_status                           # Revision stieg genau um 2 → ok
```

Jeder Write für sich prüfen; bei `changed` ab Schritt 1 neu beginnen.

## Rezept 2 — Notes ändern (Expression nicht verlieren!)

`lynx_notes_replace` ersetzt **alle** Notes eines Patterns. Vorbedingung
aus der Doku:

```
loop über offset: lynx_read scope=pattern_notes pattern_index=N offset=…
     → bis offset+gelesen == totalNotes   (leerend, in Pages)
Notes in-memory modifizieren, dabei pro Note ALLE gelesenen Felder
(start/length/pitch/velocity/… expression/chanceOne) unverändert
mitschreiben, wo nichts geändert werden soll
lynx_notes_replace pattern_index=N notes=[…]
lynx_read scope=pattern_notes pattern_index=N   # Verify
```

Pattern-ID statt Index verwenden, wenn zwischen Read und Write andere
Änderungen laufen könnten (`pattern_id=`-Form).

## Rezept 3 — Großer Umbau (viele Fakten, ein Undo)

```
lynx_transport action=stop
lynx_snapshot                       # Komplettes JSON auf Disk, Pfad merken
                                    # (mit out_dir=… direkt im Zielordner)
→ Patch gegen diese Datei entwerfen (lynx_patch akzeptiert 1–128 RFC6902-Ops,
  test/add/replace/remove; Arrays/Indizes in derselben Transaktion führen)
lynx_patch patch=[…]                # EIN Undo-Schritt
lynx_read scope=summary             # Verify statt blindes Vertrauen
```

Ohne frischen Snapshot antwortet `lynx_patch` mit `no_snapshot` — dann erst
`lynx_snapshot` (oder `lynx_read scope=summary`), nie raten.
Schreibgeschützt: Assets, Dateipfade, Plugin-States (dafür die
`lynx_plugin_*`-Tools).

## Rezept 4 — Params & Kits

```
lynx_catalog kind=instruments limit=…       # opaque IDs ('lynx:gen:Kick')
lynx_channel_create instrument_id=…         # neuer Kanal inkl. Mixer-Slot
lynx_plugin_inspect target={…}              # Parameterliste mit index-Werten
lynx_plugin_parameters target={…} parameters=[{index, value 0..1,
                             expectedValue}]   # expectedValue = Guard
```

`target` kommt wortwörtlich aus `lynx_plugin_inspect`
(`{kind:"instrument", channelIndex}` oder
`{kind:"effect", mixerIndex, effectIndex}`). Native Instrumente sind für
`plugin.parameters_set` gesperrt — dann channel-Mixer-Werte nutzen.

## Rezept 5 — Audio-Export & Projektwechsel (kein Op — Seiteneingang der CLI)

Die API kennt weder Export noch `project.open`; LYNX.exe hat aber
Headless-Modi, und `lynx_export` nutzt sie sicher verkettet:

```
lynx_transport action=stop        # der Read-Teil braucht gestopptes Playback
lynx_export format=wav            # project.read -> .lynx -> LYNX.exe --export
                                  # → {file, seconds, peak}; silent=true bei Stille
```

`lynx_export` ist read-only für die laufende Instanz (nebenläufige
UI-Arbeit ist ok; nur playback muss stehen). Formate: wav/flac/aif/mp3/
ogg/m4a. Voraussetzung: `LYNX.exe` auffindbar (Env `LYNX_EXE`).

**Bereich exportieren** (LYNX' Selection ist headless nicht erreichbar):
einfach `start_ticks`/`end_ticks` (PPQ 960, Takt 4/4 = 3840) mitgeben —
der Schnitt sitzt im Snapshot, die Instanz bleibt unberührt:

```
lynx_export format=wav end_ticks=30720   # nur die ersten 8 Takte
lynx_export format=wav start_ticks=61440 # ab Takt 16 bis Song-Ende
```

**Zielort:** `out_dir` (absolut) + `filename` (ohne Pfad/Endung) schreiben
den Ton direkt in den Projektordner des Nutzers — Pfade sind Parameter,
keine festgeschriebene Voreinstellung (Agenten-Richtlinien greifen davor);
Arbeitsdateien bleiben im Standard-Arbeitsordner:

```
lynx_export format=mp3 end_ticks=30720 out_dir="D:\musik\projekt" filename="hoerprobe"
```

**Projekt wechseln** geht nur über Neustart:

```
lynx_transport action=stop
→ NUTZER muss in der UI speichern (Strg+S) — es gibt keinen save-Ops!
testhost stop && testhost start --projekt D:\pfad\song.lynx
lynx_describe                     # neue Instanz: epoch/revision sind neu
```

**Fremde WAVs hinein** geht ebenfalls nicht (Asset-Allowlist sperrt neue
Sample-Pfade in `project.edit`): Import in der UI, danach platziert der
Agent die Audio-Clips per `lynx_playlist_edit`.

## Polling statt Push

LYNX sendet keine Events. Nach fremden Änderungen (Nutzer tippt in der UI):
`lynx_changes` (max 128, `gap:true` ⇒ Vollread nötig) oder einfach
`lynx_status` — die Revision ist der günstige Ticker.

## Wann gar nichts geht

`not_running` ⇒ LYNX startet nicht oder Remote Control ist aus
(*Settings → General → Remote control*, oder `LYNX_CONTROL_ENABLED=1`
für einen Testlauf — siehe README, Abschnitt Test-Host).
