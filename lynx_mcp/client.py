"""Client für `lynx-control/1`: Discovery, HMAC-Handshake, Ops, Paging.

Übernommen/extraht aus dem LYNX-SHARE-Referenzclient
`examples/remote_control.py` (nur Python-Stdlib). Harte Protokoll-Regeln:

- Nur TCP nach 127.0.0.1; JSON Lines, Frame <= 1 MiB, Nesting-Tiefe <= 64.
- Discovery-Datei validieren: reguläre Datei, kein Reparse-Point/Symlink,
  Owner-only-Zugriff, `protocol == "lynx-control/1"`. (Volle Prüfung: M1)
- Handshake `hello`/`challenge`/`auth`/`ready`; Server-Nachweis vor
  Client-Nachweis prüfen; Vergleich in konstanter Zeit.
- Eine Anfrage pro Verbindung (close-after-result).
- KEINE automatischen Write-Retries; Read-Antwort verloren -> idempotent
  über dieselbe Snapshot-Seite wiederholbar.
- Token niemals in Ausgaben, Logs oder Prompts.

Status: Gerüst — Discovery-Laden funktionsfähig, Handshake/Ops folgen in M1.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PROTOCOL = "lynx-control/1"
MAX_FRAME_BYTES = 1024 * 1024  # 1 MiB
MAX_DEPTH = 64


class DiscoveryError(RuntimeError):
    """Discovery-Datei fehlt, ist unberechtigbar oder fremd-protokollig."""


def default_discovery_path() -> Path:
    """Standardpfad der Discovery-Datei (Env LYNX_CONTROL_DISCOVERY hat Vorrang)."""
    env = os.environ.get("LYNX_CONTROL_DISCOVERY")
    if env:
        return Path(env)
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise DiscoveryError("APPDATA nicht gesetzt und kein --discovery übergeben")
    return Path(appdata) / "LYNX" / "control" / "connection.json"


def load_discovery(path: Path) -> dict[str, Any]:
    """Liest und prüft connection.json. Rückgabe: dict mit host/port/pid/token/protocol.

    TODO(M1): volle Härtung wie im Referenzclient — reguläre Datei, kein
    Reparse-Point, Owner-only-DACL, strikte Feldvalidierung.
    """
    if not path.is_file():
        raise DiscoveryError(
            f"Discovery-Datei nicht gefunden: {path} "
            "(LYNX läuft nicht oder Remote Control ist deaktiviert)"
        )
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscoveryError(f"Discovery-Datei unlesbar: {path}: {exc}") from exc
    if not isinstance(info, dict):
        raise DiscoveryError("Discovery-Datei enthält kein JSON-Objekt")
    if info.get("protocol") != PROTOCOL:
        raise DiscoveryError(
            f"unerwartetes Protokoll {info.get('protocol')!r}, erwarte {PROTOCOL!r}"
        )
    for field in ("port", "pid", "token"):
        if field not in info:
            raise DiscoveryError(f"Discovery-Datei fehlt Feld {field!r}")
    return info


class LynxClient:
    """Verbindet pro Anfrage einmal (close-after-result) zur LYNX-Instanz.

    TODO(M1): Handshake, Framing-Limits, pid-Prüfung, Reconnect bei
    LYNX-Prozesstod; Ops: api.describe, status, changes, project.read
    (Paging), project.edit, pattern.*, transport.*, history.*, device.state,
    instrument.catalog/effect.catalog, session.inspect, playlist.inspect.
    """

    def __init__(self, discovery_path: Path | None = None) -> None:
        self.discovery_path = discovery_path or default_discovery_path()

    def call(self, op: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError("lynx-control/1-Handshake folgt in M1")
