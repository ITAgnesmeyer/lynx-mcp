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
      "args": ["--from", "D:\\github\\LYNX-MCP", "lynx-mcp"],
      "env": { "LYNX_CONTROL_DISCOVERY": "%APPDATA%\\LYNX\\control\\connection.json" }
    }
  }
}
```

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

- Pfad zu `LYNX.exe`: Default `D:\audacity\LYNX\LYNX.exe`, überschreibbar mit
  `--exe` oder Env `LYNX_EXE`; eine Projektdatei wird optional mit `--projekt`
  zum Start übergeben.
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

Alle 29 Ops des Builds `0.1.31.1` sind in 25 MCP-Tools abgebildet (live verifiziert):

| Bereich | Tools |
| --- | --- |
| Observieren | `lynx_describe` · `lynx_status` · `lynx_session` · `lynx_changes` · `lynx_device_state` |
| Lesen | `lynx_read` (scope `summary`/`pattern_notes`/`playlist`/`session`) · `lynx_snapshot` (JSON auf Disk) · `lynx_catalog` (instruments/effects) · `lynx_plugin_inspect` |
| Dokument | `lynx_patch` (JSON Patch, 1–128 Ops = 1 Undo) |
| Typisierte Writes | `lynx_tempo_set` · `lynx_pattern_create` / `_clone` / `_set` · `lynx_notes_replace` · `lynx_channel_create` / `_set` · `lynx_mixer_set` · `lynx_instrument_replace` · `lynx_effect_load` / `_remove` · `lynx_plugin_parameters` · `lynx_playlist_edit` |
| Transport/Historie | `lynx_transport` (play/stop) · `lynx_history` (undo/redo) |

Das Fence-Tripel (`expectedProjectId`/`expectedEpoch`/`expectedRevision`) setzt der
Server **selbst** aus dem zuletzt beobachteten Read — Write-Tools brauchen es nie
als Argument, und kein Write geht ohne vorherigen Read raus (Guard-Fehler
`stale_fence`).

## Status

Frühes Projekt nach den Meilensteinen in [PLAN.md](PLAN.md) (M0–M6): M0–M3 sind
fertig und live verifiziert, M4/M5 stehen als Tools bereit (Mock-getestet;
live bisher nur Reads + No-op). Offene Punkte siehe PLAN.md §5.
