"""Kommandozeile für lynx-mcp.

Start:
    lynx-mcp            (Alias für `serve`, MCP-Server über stdio)
    python -m lynx_mcp  (derselbe Einstiegspunkt)

Unterbefehle:
    serve   MCP-Server über stdio starten (stdout gehört dem Protokoll,
            Diagnostik geht nach stderr)
    probe   Einmalig Verbindung zur laufenden LYNX-Instanz testen und
            describe/status ausgeben (kein MCP-Server)

Konfiguration:
    --discovery <pfad>  oder  Env LYNX_CONTROL_DISCOVERY
    Default: %APPDATA%\\LYNX\\control\\connection.json
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, client


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lynx-mcp",
        description=(
            "MCP-Server (stdio), der die lokale lynx-control/1-API einer "
            "laufenden LYNX-SHARE-Instanz als Tools bereitstellt."
        ),
    )
    parser.add_argument(
        "--discovery",
        metavar="PFAD",
        default=os.environ.get("LYNX_CONTROL_DISCOVERY"),
        help=(
            "Pfad zur Discovery-Datei (connection.json). "
            "Default: $LYNX_CONTROL_DISCOVERY, sonst "
            "%%APPDATA%%\\LYNX\\control\\connection.json"
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="MCP-Server über stdio starten (Default)")
    sub.add_parser(
        "probe",
        help="Discovery + Verbindung einmalig testen (describe/status, kein MCP)",
    )
    return parser


def _serve(discovery_path: Path) -> int:
    from . import server  # spätes Importieren: hält --help dependency-frei

    server.run(discovery_path=discovery_path)
    return 0


def _probe(discovery_path: Path) -> int:
    print(f"Discovery-Datei: {discovery_path}", file=sys.stderr)
    try:
        info = client.load_discovery(discovery_path)
    except client.DiscoveryError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        print(
            "Hinweis: Remote Control in LYNX aktivieren "
            "(Settings → General → Remote control, Default: aus).",
            file=sys.stderr,
        )
        return 2
    listener = client.process_image(int(info["pid"]))
    if listener is None:
        print(f"WARNUNG: Discovery-Datei verwaist — Listener-pid {info['pid']} lebt nicht "
              "(LYNX wurde ohne Bereinigung beendet?).", file=sys.stderr)
        return 2
    print(f"OK: {info['protocol']}, Port {info['port']}, pid {info['pid']} "
          f"(Prozess {info['pid']} ist {listener}).", file=sys.stderr)
    # Vollständiger Handshake + Ops folgen in M1 (client.LynxClient).
    print(
        "Handshake/Status-Abfrage ist noch nicht implementiert (Meilenstein M1).",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    discovery_path = (
        Path(args.discovery) if args.discovery else client.default_discovery_path()
    )
    command = args.command or "serve"
    if command == "probe":
        return _probe(discovery_path)
    return _serve(discovery_path)


if __name__ == "__main__":
    sys.exit(main())
