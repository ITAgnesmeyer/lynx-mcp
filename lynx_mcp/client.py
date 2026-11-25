"""Client für `lynx-control/1`: Discovery, HMAC-Handshake, Ops, Paging.

Portiert nach docs/REMOTE_CONTROL.md (Stand 2026-11). Harte Regeln:

- Nur TCP nach 127.0.0.1; JSON Lines, Op-Frames <= 1 MiB / Tiefe 64,
  Handshake-Frames <= 1 KiB / Tiefe 8.
- Discovery-Datei validieren (Protokoll, Pflichtfelder); verworfene
  Reconnects an toter Listener-pid (Schutz gegen Port-Wiederverwendung).
- Handshake `hello`/`challenge`/`auth`/`ready`; Server-Proof P wird vor
  unserem Q VERIFIZIERT; Vergleich in konstanter Zeit.
- Eine Anfrage pro Verbindung (close-after-result).
- KEINE automatischen Write-Retries; verlorene Write-Antwort = `uncertain`.
- Token niemals in Ausgaben, Logs oder Prompts.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import socket
import subprocess
from pathlib import Path
from typing import Any

PROTOCOL = "lynx-control/1"
OP_MAX_FRAME = 1024 * 1024   # 1 MiB
OP_MAX_DEPTH = 64
HS_MAX_FRAME = 1024          # 1 KiB
HS_MAX_DEPTH = 8
PAGE_DEFAULT = 32768         # Bytes pro project.read-Seite
DOC_MAX_BYTES = 64 * 1024 * 1024

# Ops mit Schreibwirkung — niemals automatisch wiederholen (PLAN.md §4).
WRITE_OPS = frozenset({
    "project.edit", "pattern.create", "pattern.clone", "pattern.set",
    "pattern.replace_notes", "transport.play", "transport.stop",
    "history.undo", "history.redo",
})


class DiscoveryError(RuntimeError):
    """Discovery-Datei fehlt, ist verwaist, unberechtigbar oder fremd-protokollig."""


class ProtocolError(RuntimeError):
    """Wire-Format, Frame-Limits oder Handshake-Verifikation verletzt."""


class LynxError(RuntimeError):
    """Von LYNX gemeldeter Fehler (code invalid|busy|changed|limit|failed|uncertain)."""

    def __init__(self, message: str, code: str = "failed", uncertain: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.uncertain = uncertain


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
    """Liest und prüft connection.json; wirft bei verwaister/fremder Datei.

    TODO(M1+): Reparse-Point-/Owner-only-DACL-Prüfung wie im Referenzclient.
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
    token = info["token"]
    if not (isinstance(token, str) and len(token) == 64
            and all(c in "0123456789abcdef" for c in token)):
        raise DiscoveryError("token hat nicht das erwartete Format (hex, 64 klein)")
    return info


def process_image(pid: int) -> str | None:
    """Bildname des Prozesses oder None (tot/unbekannt) — Windows via tasklist.

    Dient der pid-Prüfung gegen Port-Wiederverwendung (PLAN.md §1); tasklist ist
    lokalisiert, daher bytes mit errors="replace" decodieren.
    """
    try:
        raw = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
            capture_output=True, check=False,
        ).stdout
    except (OSError, ValueError):
        return None
    for line in (raw or b"").decode("ascii", errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == str(int(pid)):
            return parts[0]
    return None


def _json_depth(obj: Any, limit: int) -> int:
    """Max. Verschachtelungstiefe, iterativer Walk ( Rekursionsschutz)."""
    depth = 1
    stack: list[tuple[Any, int]] = [(obj, 1)]
    while stack:
        node, d = stack.pop()
        depth = max(depth, d)
        if depth > limit:
            return depth
        if isinstance(node, dict):
            stack.extend((v, d + 1) for v in node.values())
        elif isinstance(node, list):
            stack.extend((v, d + 1) for v in node)
    return depth


def _require_hex(value: Any, length: int, what: str) -> str:
    if not (isinstance(value, str) and len(value) == length
            and all(c in "0123456789abcdef" for c in value)):
        raise ProtocolError(f"{what} hat nicht das erwartete Format (hex, {length})")
    return value


class LynxClient:
    """Verbindet pro Anfrage einmal (close-after-result) zur LYNX-Instanz."""

    def __init__(self, discovery_path: Path | None = None, timeout: float = 10.0) -> None:
        self.discovery_path = discovery_path or default_discovery_path()
        self.timeout = timeout

    # --- Verbindung + Handshake ---------------------------------------------

    def _info(self) -> dict[str, Any]:
        info = load_discovery(self.discovery_path)
        if process_image(int(info["pid"])) is None:
            raise DiscoveryError(
                f"Discovery-Datei verwaist: Listener-pid {info['pid']} lebt nicht "
                "(LYNX ohne Bereinigung beendet?)"
            )
        return info

    def _connect(self, info: dict[str, Any]) -> socket.socket:
        sock = socket.create_connection(
            (info.get("host", "127.0.0.1"), int(info["port"])), timeout=self.timeout
        )
        try:
            self._handshake(sock, info["token"])
        except Exception:
            sock.close()
            raise
        return sock

    @staticmethod
    def _handshake(sock: socket.socket, token: str) -> None:
        c = secrets.token_hex(16)  # 32 hex-Zeichen
        _send_line(sock, {"type": "hello", "protocol": PROTOCOL, "nonce": c},
                   HS_MAX_FRAME, HS_MAX_DEPTH)
        ch = _recv_line(sock, HS_MAX_FRAME, HS_MAX_DEPTH)
        if ch.get("type") != "challenge" or ch.get("protocol") != PROTOCOL:
            raise ProtocolError("kein challenge-Frame empfangen")
        s = _require_hex(ch.get("nonce"), 32, "server nonce")
        p = _require_hex(ch.get("proof"), 64, "server proof")
        key = token.encode("ascii")  # ASCII-Text des Tokens, nicht die Bytes
        expect = hmac.new(key, f"{PROTOCOL}\nserver\n{c}\n{s}".encode("ascii"),
                          hashlib.sha256).hexdigest()
        if not hmac.compare_digest(p, expect):
            # Server-Proof VOR unserem Q prüfen — sonst kein Credential-Leak.
            raise ProtocolError("Server-Proof ungültig — Verbindung verworfen")
        q = hmac.new(key, f"{PROTOCOL}\nclient\n{c}\n{s}".encode("ascii"),
                     hashlib.sha256).hexdigest()
        _send_line(sock, {"type": "auth", "proof": q}, HS_MAX_FRAME, HS_MAX_DEPTH)
        rdy = _recv_line(sock, HS_MAX_FRAME, HS_MAX_DEPTH)
        if rdy.get("type") != "ready" or rdy.get("protocol") != PROTOCOL:
            raise ProtocolError("kein ready-Frame empfangen")

    # --- Anfragen ------------------------------------------------------------

    def request(self, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Eine Anfrage pro Verbindung; Ergebnis oder LynxError.

        Writes werden niemals automatisch wiederholt; Aufrufer tragen die
        Verantwortung (PLAN.md §4).
        """
        info = self._info()
        sock = self._connect(info)
        try:
            _send_line(sock, {"op": op, "args": args or {}}, OP_MAX_FRAME, OP_MAX_DEPTH)
            reply = _recv_line(sock, OP_MAX_FRAME, OP_MAX_DEPTH)
        finally:
            sock.close()
        if reply.get("ok") is True:
            result = reply.get("result")
            if not isinstance(result, dict):
                raise ProtocolError(f"{op}: result ist kein Objekt")
            return result
        raise LynxError(
            str(reply.get("error", "unbekannter Fehler")),
            code=str(reply.get("code", "failed")),
            uncertain=bool(reply.get("uncertain")),
        )

    def call(self, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request(op, args)

    # --- Paging über project.read ---------------------------------------------

    def project_read_full(self, max_pages: int = 16,
                          page_limit: int = PAGE_DEFAULT) -> tuple[dict, dict]:
        """Komplettes Dokument aus einem Snapshot lesen; (projekt_json, fence-meta).

        Fence-meta: snapshotId, documentHash, projectId, controlEpoch, revision.
        Achtung: Vollsnapshots erfordern gestopptes Playback (Doku) und können
        alte Snapshots verdrängen.
        """
        first = self.request("project.read", {"limit": page_limit})
        chunks = [base64.b64decode(first["data"])]
        snapshot_id = first["snapshotId"]
        doc_hash = first["documentHash"]
        offset = int(first.get("offset", 0)) + len(chunks[-1])
        total = int(first["totalBytes"])
        pages = 1
        while first.get("nextOffset") is not None:
            if pages >= max_pages:
                raise LynxError(
                    f"paging cap erreicht ({max_pages} Seiten) — Snapshot mit "
                    "mehr Seiten oder lynx_snapshot verwenden", code="limit")
            first = self.request("project.read", {
                "snapshotId": snapshot_id, "expectedDocumentHash": doc_hash,
                "offset": int(first["nextOffset"]), "limit": page_limit})
            chunks.append(base64.b64decode(first["data"]))
            offset = int(first["offset"]) + len(chunks[-1])
            pages += 1
        blob = b"".join(chunks)
        if len(blob) != total or total > DOC_MAX_BYTES:
            raise ProtocolError(f"snapshot größe {len(blob)} != totalBytes {total}")
        if hashlib.sha256(blob).hexdigest() != doc_hash:
            raise ProtocolError("documentHash-Verifikation fehlgeschlagen")
        project = json.loads(blob.decode("utf-8"))
        meta = {k: first.get(k) for k in
                ("snapshotId", "documentHash", "projectId", "controlEpoch", "revision")}
        return project, meta

    def project_read_page(self, snapshot_id: str, doc_hash: str, offset: int,
                          page_limit: int = PAGE_DEFAULT) -> dict:
        return self.request("project.read", {
            "snapshotId": snapshot_id, "expectedDocumentHash": doc_hash,
            "offset": offset, "limit": page_limit})


def _send_line(sock: socket.socket, obj: dict, max_frame: int, max_depth: int) -> None:
    if _json_depth(obj, max_depth) > max_depth:
        raise ProtocolError("frame über Tiefe-Limit")
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    if len(data) + 1 > max_frame:
        raise ProtocolError("frame über Größenlimit")
    sock.sendall(data + b"\n")


def _recv_line(sock: socket.socket, max_frame: int, max_depth: int) -> dict:
    buf = bytearray()
    while True:
        b = sock.recv(65536)
        if not b:
            raise ProtocolError("Verbindung vor Frame-Ende geschlossen")
        buf.extend(b)
        if b"\n" in buf:
            line, _, rest = buf.partition(b"\n")
            if rest:
                raise ProtocolError("mehr als ein Frame pro Verbindung empfangen")
            break
        if len(buf) > max_frame:
            raise ProtocolError("frame über Größenlimit")
    if len(buf) > max_frame:
        raise ProtocolError("frame über Größenlimit")
    try:
        obj = json.loads(buf.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"kein gültiges UTF-8 JSON: {exc}") from exc
    if not isinstance(obj, dict) or _json_depth(obj, max_depth) > max_depth:
        raise ProtocolError("frame kein Objekt / über Tiefenlimit")
    return obj
