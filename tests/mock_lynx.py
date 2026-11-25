"""LYNX Mock-Listener: implementiert lynx-control/1 für Tests (nur Stdlib).

Bindet 127.0.0.1:ephemeral, schreibt eine connection.json und beantwortet
nach vollständigem, korrekt verifiziertem Handshake eine Op pro Verbindung
(close-after-result) mit festen oder dynamischen (Callable) Ergebnissen.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import socket
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROTOCOL = "lynx-control/1"


class MockLynx(threading.Thread):
    def __init__(self, token: str | None = None) -> None:
        super().__init__(daemon=True)
        self.token = token or secrets.token_hex(32)
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(8)
        self.port = self.server.getsockname()[1]
        self.handlers: dict[str, dict | Callable[[dict], dict]] = {}
        self.requests: list[dict[str, Any]] = []
        self.client_proofs_ok: list[bool] = []
        self._stop = threading.Event()

    # --- Konfiguration -------------------------------------------------------

    def respond(self, op: str, result: dict | Callable[[dict], dict]) -> None:
        self.handlers[op] = result

    def error(self, op: str, message: str, code: str, uncertain: bool = False) -> None:
        self.respond(op, lambda a, m=message, c=code, u=uncertain: {
            "__error__": {"error": m, "code": c, "uncertain": u}})

    def write_discovery(self, path: Path, pid: int | None = None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "protocol": PROTOCOL, "host": "127.0.0.1", "port": self.port,
            "pid": pid if pid is not None else os.getpid(),
            "appVersion": "0.0.0-mock", "token": self.token,
        }), encoding="utf-8")
        return path

    # --- Server-Schleife ------------------------------------------------------

    def run(self) -> None:
        self.server.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn, _ = self.server.accept()
            except TimeoutError:  # socket.timeout ist seit 3.10 Alias davon
                continue
            except OSError:
                break
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.server.close()
        except OSError:
            pass

    def _serve(self, conn: socket.socket) -> None:
        # Achtung: NICHT `with conn:` um den makefile-Block wickeln — das hält
        # das Socket-Lock und readline() im SocketIO Deadlock-Timeout.
        try:
            with conn.makefile("rwb") as f:
                hello_line = f.readline()
                if not hello_line:
                    return
                hello = json.loads(hello_line.decode("utf-8"))
                if hello.get("type") != "hello" or hello.get("protocol") != PROTOCOL:
                    return
                if not self._handshake(f, hello):
                    return
                line = f.readline()
                if not line:
                    return
                req = json.loads(line.decode("utf-8"))
                self.requests.append(req)
                handler = self.handlers.get(req.get("op", ""))
                if handler is None:
                    out = {"ok": False, "error": f"unknown op {req.get('op')!r}",
                           "code": "invalid", "uncertain": False}
                elif isinstance(handler, dict):
                    out = {"ok": True, "result": handler, "id": None}
                else:
                    res = handler(req.get("args", {}))
                    if "__error__" in res:
                        out = {"ok": False, **res["__error__"]}
                    else:
                        out = {"ok": True, "result": res}
                f.write(json.dumps(out).encode("utf-8") + b"\n")
                f.flush()  # Ergebnis vor dem Schließen tatsächlich senden
        except Exception:
            pass  # Client-Tests erwarten saubere Trennung, keine Tracebacks
        finally:
            conn.close()

    def _handshake(self, f, hello: dict) -> bool:
        if hello.get("type") != "hello" or hello.get("protocol") != PROTOCOL:
            return False
        c = hello["nonce"]
        s = secrets.token_hex(16)
        key = self.token.encode("ascii")
        p = hmac.new(key, f"{PROTOCOL}\nserver\n{c}\n{s}".encode(), hashlib.sha256).hexdigest()
        f.write(json.dumps({"type": "challenge", "protocol": PROTOCOL,
                            "nonce": s, "proof": p}).encode() + b"\n")
        f.flush()  # buffered writer: ohne flush sieht der Client den Frame nie
        auth = json.loads(f.readline().decode("utf-8"))
        q_expect = hmac.new(key, f"{PROTOCOL}\nclient\n{c}\n{s}".encode(),
                            hashlib.sha256).hexdigest()
        ok = hmac.compare_digest(auth.get("proof", ""), q_expect)
        self.client_proofs_ok.append(ok)
        if not ok:
            return False
        f.write(json.dumps({"type": "ready", "protocol": PROTOCOL}).encode() + b"\n")
        f.flush()
        return True


def make_read_pages(document: bytes, page_size: int):
    """Handler-Fabrik für paginierte project.read-Ergebnisse wie in der Doku."""
    doc_hash = hashlib.sha256(document).hexdigest()
    snapshot_id = "snap-mock-1"

    def handler(args: dict) -> dict:
        offset = int(args.get("offset", 0))
        limit = int(args.get("limit", 32768))
        if offset:
            if args.get("snapshotId") != snapshot_id:
                return {"__error__": {"error": "snapshot abgelaufen/falsch",
                                      "code": "changed", "uncertain": False}}
            if args.get("expectedDocumentHash") != doc_hash:
                return {"__error__": {"error": "documentHash stimmt nicht",
                                      "code": "invalid", "uncertain": False}}
        chunk = document[offset:offset + limit]
        nxt = offset + len(chunk)
        return {"snapshotId": snapshot_id, "documentHash": doc_hash,
                "encoding": "base64", "data": base64.b64encode(chunk).decode(),
                "offset": offset, "totalBytes": len(document),
                "nextOffset": nxt if nxt < len(document) else None,
                "projectId": "proj-mock", "controlEpoch": "epoch-1", "revision": 7}

    return handler
