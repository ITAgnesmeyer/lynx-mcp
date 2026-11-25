# lynx-mcp

MCP-Server (Model Context Protocol, **stdio**), der die lokale `lynx-control/1`-API
einer laufenden [LYNX-SHARE](https://github.com/Ka1-S/LYNX-SHARE)-Instanz für
Sprachmodelle/Agenten als Tools bereitstellt — sicher, kontextsparsam und
undo-freundlich.

Der Server bindet **kein eigenes Netzwerk-Listener**: Er spawned keinen Port und
verbindet sich nur als TCP-Client nach `127.0.0.1` zu dem von LYNX geöffneten
Loopback-Port. Das Zugangs-Token bleibt im Serverprozess und taucht in keiner
Tool-Ausgabe, keinem Log und keinem Schema auf. Details in [PLAN.md](PLAN.md).

## Voraussetzungen

- Python ≥ 3.10 bzw. [`uv`](https://docs.astral.sh/uv/)
- Laufende LYNX-Instanz mit aktivierter Remote Control
  (*Settings → General → Remote control*, Default: **aus**; alternativ
  `LYNX_CONTROL_ENABLED=1` für einen Run)
- Discovery-Datei `%APPDATA%\LYNX\control\connection.json`
  (überschreibbar via `--discovery` / Env `LYNX_CONTROL_DISCOVERY`)

## Start über uv/uvx (beabsichtigt)

Der Paketname (`lynx-mcp`) entspricht dem Console-Script, damit die üblichen
uv-Startwege funktionieren:

```console
uvx --from D:\github\LYNX-MCP lynx-mcp        # lokal aus diesem Repo
uv tool install D:\github\LYNX-MCP && lynx-mcp   # dauerhaft installiert
uv run lynx-mcp --help                      # innerhalb des Repos
```

Nach einem Publish auf PyPI genügt `uvx lynx-mcp`.

### MCP-Client-Konfiguration (Beispiel)

```json
{
  "mcpServers": {
    "lynx": {
      "command": "uvx",
      "args": ["--from", "<PFAD ZU DIESEM REPO>", "lynx-mcp"],
      "env": {
        "LYNX_CONTROL_DISCOVERY": "%APPDATA%\\LYNX\\control\\connection.json",
        "LYNX_MCP_OUT_DIR": "%LOCALAPPDATA%\\lynx-mcp\\out"
      }
    }
  }
}
```

(`--from` entfällt, sobald das Paket über PyPI installierbar ist; alle
Env-Variablen sind optional — Defaults siehe Abschnitt Test-Host.)

### Skill für Agenten (optional)

Unter [`skills/lynx-remote-control/SKILL.md`](skills/lynx-remote-control/SKILL.md)
liegt ein kurzes Workflow-Skill (OpenCode/Claude-Code-Format) für Clients,
die Skills unterstützen: Lese-Schreib-Zyklus, Notes-Replace ohne
Expression-Verlust, Snapshot→Patch→Undo-Choreographie. MCP-Clients ohne
Skill-Support brauchen es nicht — die Regeln stecken auch in den
Tool-Beschreibungen.

## Entwicklung / klassische Installation

```console
pip install -e .
python -m lynx_mcp --help
python -m lynx_mcp probe     # Verbindungstest gegen eine laufende Instanz
python -m lynx_mcp serve     # MCP-Server über stdio (Default)
```

## Test-Host (LYNX starten/beenden)

Zum Entwickeln und für Smoke-Tests kannst du LYNX mit aktivierter Remote Control
über die Environment-Variable `LYNX_CONTROL_ENABLED=1` starten:

```console
uv run python -m lynx_mcp.testhost start        # detachter Run, Remote Control an,
                                                # wartet auf die Discovery-Datei
uv run python -m lynx_mcp.testhost status        # Instanz-, exe- und Discovery-Lage
uv run python -m lynx_mcp.testhost stop          # nur die von testhost gestartete Instanz
```

- **Keine festen Pfade:** `LYNX.exe` wird über Env `LYNX_EXE` (oder `--exe`)
  gesetzt; ohne Angabe sucht testhost nur die üblichen Installationsorte
  (`%LOCALAPPDATA%\Programs\LYNX`, `%ProgramFiles%\LYNX`). Bei **portabler**
  Installation (kein Standardort) genügt `setx LYNX_EXE "D:\pfad\zu\LYNX.exe"`.
  Eine Projektdatei lässt sich optional mit `--projekt` übergeben.
- Snapshots (`lynx_snapshot`) landen im Quellen-Checkout unter `out/`, sonst
  unter `%LOCALAPPDATA%\lynx-mcp\out` — mit Env `LYNX_MCP_OUT_DIR` frei wählbar.
- `stop` beendet ausschließlich Instanzen, die testhost selbst gestartet hat
  (PID-State-Datei + Bildnamen-Prüfung gegen PID-Wiederverwendung).
- Verwaiste Discovery-Dateien (LYNX ohne Bereinigung beendet) erkennen
  `start`/`status`/`probe` an der toten Listener-PID.

## CLI

```
lynx-mcp [--discovery PFAD] {serve, probe}

  serve   MCP-Server über stdio starten (Default)
  probe   Discovery + Verbindung einmalig testen (kein MCP-Server)
```

Der Test-Host hat eine eigene CLI: `python -m lynx_mcp.testhost {start,stop,status}`.

## Tools (vollständige Remote-Control-Fläche)

Alle 29 Ops des Builds `0.1.31.1` sind in 25 MCP-Tools abgebildet (live
verifiziert); `lynx_export` ergänzt als 26. Tool den Headless-Export von
LYNX.exe (kein Op, aber aus der API sauber ableitbar, s. unten):

| Bereich | Tools |
| --- | --- |
| Observieren | `lynx_describe` · `lynx_status` · `lynx_session` · `lynx_changes` · `lynx_device_state` |
| Lesen | `lynx_read` (scope `summary`/`pattern_notes`/`playlist`/`session`) · `lynx_snapshot` (JSON auf Disk) · `lynx_catalog` (instruments/effects) · `lynx_plugin_inspect` |
| Dokument | `lynx_patch` (JSON Patch, 1–128 Ops = 1 Undo) |
| Typisierte Writes | `lynx_tempo_set` · `lynx_pattern_create` / `_clone` / `_set` · `lynx_notes_replace` · `lynx_channel_create` / `_set` · `lynx_mixer_set` · `lynx_instrument_replace` · `lynx_effect_load` / `_remove` · `lynx_plugin_parameters` · `lynx_playlist_edit` |
| Transport/Historie | `lynx_transport` (play/stop) · `lynx_history` (undo/redo) |
| Export | `lynx_export` (Audio-Render: wav/flac/ogg/mp3/aif/m4a) |

Das Fence-Tripel (`expectedProjectId`/`expectedEpoch`/`expectedRevision`) setzt der
Server **selbst** aus dem zuletzt beobachteten Read — Write-Tools brauchen es nie
als Argument, und kein Write geht ohne vorherigen Read raus (Guard-Fehler
`stale_fence`).

### Audio-Export (`lynx_export`)

Die Remote-Control-API selbst hat keinen Export-Ops — aber LYNX.exe bringt
einen fensterlosen Export-Modus mit (`LYNX.exe --export <in> <out>`).
`lynx_export` verkettet beides sicher:

1. **Vollread** der laufenden Session (`project.read`, verlangt gestopptes
   Playback) → natives Projekt-JSON (`.lynx`) im Snapshot-Ordner,
2. **neuer LYNX-Prozess** rendert daraus WAV (24 bit), FLAC, OGG, MP3
   (320 kbit/s), AIFF oder M4A/AAC — die laufende Instanz wird dabei nicht
   angefasst (der Export-Zweig verlässt LYNX' `initialise`, bevor der
   Remote-Control-Listener startet),
3. **Report-Parsing**: `result`/`peak`/`song_seconds` aus der von LYNX
   geschriebenen `.txt` landen strukturiert in der Antwort.

Voraussetzung ist der Pfad zu `LYNX.exe` (Env `LYNX_EXE`, sonst
Installationssuche — wie beim Test-Host). Ein stiller Render gilt als Fehler
(`silent: true` mit Grund) — die Datei existiert dann trotzdem. Ein Timeout
bricht den Exportprozess ab und meldet `uncertain` (Datei teilgeschrieben),
also nicht blind wiederholen.

**Herkommen von Audio geht umgekehrt nicht über die API**: Neue Sample-/
Asset-Pfade sind in `project.edit` allowlist-seitig gesperrt („cannot
introduce new sample/zone paths") — Imports bleiben der UI vorbehalten;
danach platziert der Agent Audio-Clips frei über `lynx_playlist_edit`.

## Status

Frühes Projekt nach den Meilensteinen in [PLAN.md](PLAN.md) (M0–M6): M0–M3 sind
fertig und live verifiziert, M4/M5 stehen als Tools bereit (Mock-getestet;
live bisher nur Reads + No-op). Offene Punkte siehe PLAN.md §5.

## Lizenz

MIT ([LICENSE](LICENSE)). Die Lizenzen der eingebundenen Drittkomponenten —
inklusive Hinweis auf LYNX SHARE (AGPL-3.0, nicht enthalten, nur API-Fernnutzung) —
stehen in [THIRD_PARTY.md](THIRD_PARTY.md).
