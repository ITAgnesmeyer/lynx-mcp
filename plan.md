# Plan: LYNX Remote Control → MCP-Server (`lynx-mcp`)

Ziel: Ein MCP-Server (Model Context Protocol, stdio), der die lokale `lynx-control/1`-API
einer laufenden LYNX-SHARE-Instanz für Sprachmodelle/Agenten als Tools bereitstellt —
sicher, kontextsparsam und undo-freundlich.

Bezugsquellen (Stand 2026-11):

- Protokoll: <https://github.com/Ka1-S/LYNX-SHARE/blob/main/docs/REMOTE_CONTROL.md> (`lynx-control/1`)
- Referenz-Client (nur Python-Stdlib): `examples/remote_control.py` im Repo
- **Test-Installation des Programms: `D:\audacity\LYNX`** (`LYNX.exe`, Discovery:
  `%APPDATA%\LYNX\control\connection.json`) — nur Bezugsobjekt zum Testen, **nicht** der
  Ablageort dieses Projekts (siehe §0)
- Voraussetzungen am Server: Remote Control in LYNX aktiviert (*Settings → General → Remote
  control*, Default: **aus**; alternativ `LYNX_CONTROL_ENABLED=1` für einen Run)

---

## 0. Projektlage und Startpunkt

- Dieses Dokument (`plan.md`, abgelegt unter `D:\audacity\LYNX\MCP`) ist der **Startpunkt
  für ein eigenes Repo**. Die Doku wird in das neue Repo übernommen (dort z. B. als
  `docs/PLAN.md` oder `PLAN.md`) und von dort weiter gepflegt.
- Für `lynx-mcp` wird ein **eigener Ordner außerhalb des aktuellen Workingdirs**
  (`D:\audacity\LYNX`) angelegt — das Repo enthält nur Server-Code, Tests und Doku,
  **keine** Programmdateien von LYNX.
- `D:\audacity\LYNX` bleibt davon unberührt: Es ist die **Installationsort der
  LYNX.exe und dient als Testumgebung** (Smoke-Tests, Discovery-Datei, Demo.lynx).

---

## 1. Grundsatzentscheidungen

| Thema | Entscheidung | Begründung |
|---|---|---|
| Sprache/Laufzeit | Python ≥ 3.10, offizielles `mcp`-SDK (`mcp[cli]`) | Der Referenz-Client ist Python/Stdlib; Handshake, Paging und Fence-Logik werden direkt übernommen |
| Transport | MCP über **stdio** | Kein额外 Netzwerk-Listener; der einzige TCP-Socket bleibt LYNX' Loopback-Listener |
| Token-Handling | Token wird **nur im Serverprozess** gelesen, taucht in keiner Tool-Ausgabe, keinem Log, keinem Schema auf | Vorgabe aus REMOTE_CONTROL.md: „Never put it in a command argument, log, model prompt or request" |
| Tool-Granularität | Typisierte Tools für die häufigsten Ops + **ein** generisches Patch-Tool | Typisierte Ops (`pattern.*`) erledigen natives Referenz-Remapping korrekt; `project.edit` bleibt als Fluchttür |
| Passthrough-Tool `lynx_op`? | **Nein** (initial) | Würde Frames/Größenlimits und Token-Leaks unnötig dem Modell überlassen; `api.describe` liefert die Ops-Liste stattdessen an `lynx_describe` |
| Voll-Snapshot `project.read` | Nur als **Zusammenfassungs-Tool** mit Paging, niemals alles ins Kontext | Bis 64 MiB Dokument; Kontext-Limit |
| Verbindung | Lazy: erster Tool-Aufruf liest Discovery, verbindet, validiert `pid`; reconnect bei Tod des LYNX-Prozesses | `pid`-Prüfung gegen Port-Wiederverwendung |

## 2. Architektur

```
┌─────────────┐  MCP/stdio   ┌──────────────────────┐  TCP 127.0.0.1  ┌───────────┐
│ MCP-Client  │ ◄──────────► │  lynx-mcp (Python)   │ ◄─────────────► │  LYNX.exe │
│ (Agent/App) │              │                      │  lynx-control/1 │  Listener │
└─────────────┘              │  ├ discovery.py      │  JSON lines     └───────────┘
                             │  ├ client.py  (Handshake, Ops, Paging)│
                             │  ├ fence.py   (projectId/epoch/revision,│
                             │  │             snapshotId/documentHash cache)
                             │  ├ summarize.py (Projekt-JSON → Kurzstruktur)
                             │  └ server.py  (Tool-Definitionen, @mcp.tool)
                             └──────────────────────┘
```

Module:

1. **`client.py`** — aus `examples/remote_control.py` extrahiert/übernommen:
   Discovery-Datei validieren (reguläre Datei, kein Reparse-Point, Owner-only DACL,
   `protocol=="lynx-control/1"`), HMAC-Handshake (`hello`/`challenge`/`auth`/`ready`,
   Server-Nachweis **vor** Client-Nachweis prüfen, konstante Zeit), 1-MiB-/Depth-64-Limits,
   eine Anfrage pro Verbindung (close-after-result), **keine automatischen Write-Retries**.
2. **`fence.py`** — Session-Gedächtnis: letzte beobachtete `(projectId, controlEpoch,
   revision)` und aktive Snapshots. Schreib-Tools verweigern ohne frischen Read-Zustand
   mit klarer Anweisung („erst lynx_read/lynx_status aufrufen"). `changed`-Fehler markieren
   den Cache als stale.
3. **`summarize.py`** — `project.read`-JSON → Kurzdarstellung: Tempo/Meter, Channel-Namen
   + IDs, Pattern-Liste (Name, Länge, Notencount), Arrangements, Mixer-Tracks, Automationen —
   mit Stable-IDs/Referenzpfaden für Folgereads (`/patterns/3/notes/…`), plus Byte-Hash.
4. **`server.py`** — MCP-Werkzeugfläche (Abschnitt 3), Fehler-Mapping auf lesbare Texte.

## 3. Tool-Oberfläche (v1)

| Tool | Parameter | Wrapper um | Bemerkung |
|---|---|---|---|
| `lynx_describe` | – | `api.describe` |返回列表 der vom Build unterstützten Ops/Capabilities; Tools daraus dynamisch annotieren |
| `lynx_status` | – | `status` | Identität, `revision`, Tempo, Meter, Transport, Position, Pattern, Counts |
| `lynx_changes` | `fromRevision`, `limit?` | `changes` | max 128; `gap` → Hinweis „Vollread nötig" |
| `lynx_read` | `scope: summary\|pattern_notes\|playlist\|session`, `patternIndex?`, `offset?/cursor?` | `project.read` (Paging) / `pattern.notes` / `playlist.inspect` / `session.inspect` | `summary` ist Default; Rohe Voll-JSON-Seiten nur auf expliziten Wunsch |
| `lynx_snapshot` | `maxPages?` | `project.read` | kompletter Snapshot auf Disk (`out/`-Ordner neben Server, Pfad zurück) statt Kontext-Flut |
| `lynx_patch` | `patch` (RFC 6902 Array, 1–128 Ops) | `project.edit` | Fence-Felder werden **serverseitig** eingesetzt; Antwort: `changed`, `operationCount`, neue Revision, `documentHash` |
| `lynx_pattern_create` | `index?`, `name?`, `lengthTicks?` | `pattern.create` | Capability-Check via `describe` |
| `lynx_pattern_clone` | `index`, `name?` | `pattern.clone` | |
| `lynx_pattern_set` | `index`, `name?`, `lengthTicks?` | `pattern.set` | |
| `lynx_notes_replace` | `patternIndex`/`patternId`, `notes` (vollständige Felder inkl. defaults) | `pattern.replace_notes` | Vorbedingung: leerender Read derselben Notes (Doku: expression nicht verlieren) |
| `lynx_param_set` | `device`, `parameter`, `value01` (Batch) | typisierte Parameter-Ops | normalisierte `0..1`-Werte |
| `lynx_transport` | `action: play\|stop` | `transport.play/stop` | stop funktioniert auch bei stale Fence (dokumentiert) |
| `lynx_history` | `action: undo\|redo`, `expectedDeviceStateHash?` | `history.undo/redo` | Ownership des Top-Steps erforderlich (Doku-Hinweis im Tool-Text) |
| `lynx_device_state` | – | `device.state` | Hash-only |
| `lynx_catalog` | `kind: instruments\|effects`, `cursor?` | `instrument.catalog` / `effect.catalog` | Paginiert |

Reserviert für v2: `ui.*`/`session.*` (nur im `--demo`-Run sichtbar; über `describe`
automatisch als Capability erkannt), `device_state_hash`-Guards in `lynx_patch`.

Jedes Tool-Schema enthält die harten Regeln als Beschreibung:
*Schreiboperationen erfordern gestopptes Playback; niemals `uncertain`-Fehler automatisch
wiederholen; nach strukturellem Change immer neu lesen; Patch ändert keine Assets/Pfade/
Plugin-States (Allowlist).*

## 4. Sicherheit & Fehlerbehandlung

- **Credentials**: Discovery-Pfad konfigurierbar (`--discovery` / Env `LYNX_CONTROL_DISCOVERY`),
  Dateiberechtigungen wie der Referenz-Client prüfen (regular file, kein Reparse/Symlink,
  owner-only). Ausgabe-Pfade des Servers (Logs) enthalten nie Token/proofs.
- **Kein Retry von Writes**: Nur Reads dürfen nach Verbindungsabbruch wiederholt werden
  (idempotent über dieselbe Snapshot-Seite). Write-Antwort verloren → Ergebnis als
  `uncertain` durchreichen, Projekt-Zustand erst per Read klären.
- **Stale-Fence-Politik**: Server erzwingt Read-before-Write pro Session; Modell kann
  veraltete Triple gar nicht erst mitschicken (Option wird ignoriert und serverseitig gesetzt).
- **Ressourcen-Limits**: Paging-Kap pro Aufruf (z. B. ≤ 16 Seiten à 32 KiB), Tool-Antworten
  auf ~200 KiB gekürzt mit `truncated`-Flag und Cursor.
- **Betrieb**: Server startet ohne LYNX und meldet „not running / remote control off" als
  freundlichen Status statt Crash (`lynx_status` → klare Meldung).

## 5. Meilensteine

| # | Deliverable | Akzeptanz |
|---|---|---|
| M0 | Repo-Skelett im neuen Repo-Ordner außerhalb von `D:\audacity\LYNX` (§0): `lynx_mcp/`, `pyproject.toml`, `README.md`, `PLAN.md` (diese Doku) | `pip install -e .`, `python -m lynx_mcp --help` |
| M1 | `client.py` + CLI-Rauchtest gegen laufende Instanz | `status`/`describe` liefern korrekte JSON über Discovery+Handshake; Token-Handling wie Vorlage; Negativtest: manipuliertes Discovery-File wird abgelehnt |
| M2 | `fence.py` + Read-Pipeline (`summary`, Paging, `snapshot` auf Disk) | Vollständiger Read eines mittelgroßen Projekts (Demo.lynx) ohne Kontext-Überschwemmung; `documentHash`-Verifikation |
| M3 | MCP-Server, read-only Tools (`describe/status/changes/read/catalog/device_state`) | In OpenCode/Claude-Desktop einbindbar; Agent kann „Wie ist das Projekt gebaut?" beantworten |
| M4 | Schreib-Tools: `transport`, `pattern.*`, `notes_replace`, `param_set`, `history` | Agent legt Pattern an, ersetzt Notes, spielt; jeder Schritt = 1 Undo; Undo-Ritt funktioniert |
| M5 | `lynx_patch` (JSON Patch) + Edge-Cases | Tempo+Umbenennung in **einem** Undo-Schritt; dangling refs/`changed`/`busy`/`uncertain` sauber gemappt; Write-once-Verhalten nachgewiesen |
| M6 | Härtung & Doku | Tool-Beschreibungen mit Protocol-Regeln; Logs anonymisiert; Config-Doku; Optional: Upstream-PR als `examples/mcp_server.py` |

Geschätzter Aufwand: M0–M2 ≈ 0,5 Tage, M3 ≈ 0,5 Tage, M4–M5 ≈ 1–1,5 Tage (Testarbeit mit
laufendem LYNX), M6 ≈ 0,5 Tage.

## 6. Projektlayout

Repo-Wurzel ist der **neu anzulegende Ordner außerhalb von `D:\audacity\LYNX`** (Pfad noch
zu wählen, z. B. `D:\projects\lynx-mcp\`):

```
<repo-root>\                    (eigenes Repo, außerhalb von D:\audacity\LYNX)
  PLAN.md                 (Startpunkt: diese Datei, hierher übernommen — siehe §0)
  pyproject.toml          (Console-Script: lynx-mcp)
  README.md               (Setup: Remote Control aktivieren, MCP-Config-Snippet)
  lynx_mcp/
    __main__.py           (CLI: serve | probe)
    client.py             (lynx-control/1: discovery, handshake, ops, paging)
    fence.py              (revision/snapshot-Fence-Cache)
    summarize.py          (Projekt-JSON → Kurzstruktur)
    server.py             (MCP-Tools, v1-Menge aus §3)
  out/                    (von `lynx_snapshot` beschriebene Projekt-JSONs)
  tests/                  (Mock-Listener: Handshake + canned Ops gegen client.py)
```

MCP-Client-Konfiguration (Beispiel, OpenCode/`config.json`-Syntax):

```json
{ "mcpServers": { "lynx": { "command": "python",
    "args": ["-m", "lynx_mcp"],
    "env": { "LYNX_CONTROL_DISCOVERY": "%APPDATA%\\LYNX\\control\\connection.json" } } } }
```

## 7. Risiken & offene Punkte

| Risiko | Maßnahme |
|---|---|
| Repo-Doku (`main`) ist neuer als installierte Version 0.1.31.x | `api.describe` als Source of Truth; Features capability-gated |
| `changes`-Gap → Modell handelt auf veralteter Struktur | Server erzwingt Re-Read nach `gap:true` (Tool-Fehler mit Anweisung) |
| Zu große Notelists im Kontext | `pattern.notes` paginiert; Warnung bei > 2 000 Notes pro Aufruf |
| Agent toggled Remote Control nicht selbst an | Klare Fehlermeldung + Hinweis auf Setting; `probe`-CLI-Command zum Testen |
| Virenscanner/Firewall-Warnung beim Loopback-Verbinden | Nur `127.0.0.1`, dokumentiert; kein eigener Listen-Port des Servers |

## 8. Nicht-Ziele (v1)

- Keinownes HTTP-/WebSocket-Listening des MCP-Servers (nur LYNX' Loopback)
- Kein Skripten von außen (pocketpy ist nicht Teil der Remote-API)
- Kein Asset-Import, kein Render/Speichern per API (Protokoll kann das nicht)
- Keine UI-Automatisierung (`ui.*`) außer im dokumentierten Demo-Modus
