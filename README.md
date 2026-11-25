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

### Entwicklung / klassische Installation

```console
pip install -e .
python -m lynx_mcp --help
python -m lynx_mcp probe     # Verbindungstest gegen eine laufende Instanz
python -m lynx_mcp serve     # MCP-Server über stdio (Default)
```

## CLI

```
lynx-mcp [--discovery PFAD] {serve, probe}

  serve   MCP-Server über stdio starten (Default)
  probe   Discovery + Verbindung einmalig testen (kein MCP-Server)
```

## Status

Frühes Projekt nach den Meilensteinen in [PLAN.md](PLAN.md) (M0–M6):
Repo-Skelett steht; Client-Handshake (M1), Read-Pipeline (M2), MCP-Tools
(M3–M5) sind partiell als Stubs angelegt.
