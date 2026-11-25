"""lynx-mcp Test-Host: startet/beendet LYNX.exe für Tests mit Remote Control.

LYNX wird abgekoppelt (detached) vom Tool-Prozess mit der Umgebungsvariable
LYNX_CONTROL_ENABLED=1 gestartet. Die PID wird in einer State-Datei
(%LOCALAPPDATA%\\lynx-mcp\\testhost.json) festgehalten, damit `stop` ausschließlich
von diesem Tool gestartete Instanzen beendet — nie eine fremde Instanz.

Nur für Testzwecke; ersetzt keine Produkthinweise zum Aktivieren von
Remote Control in LYNX (Settings → General → Remote control).

Verwendung:
    python -m lynx_mcp.testhost start [--exe PFAD] [--projekt DATEI]
                                      [--no-wait] [--timeout SEK]
    python -m lynx_mcp.testhost stop  [--force] [--timeout SEK]
    python -m lynx_mcp.testhost status

Env: LYNX_EXE             Pfad zu LYNX.exe (ohne Angabe werden die üblichen
                               Installationsorte gesucht, s. _candidate_exes)
     LYNX_CONTROL_DISCOVERY   Discovery-Datei (Default %APPDATA%\\LYNX\\control)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, TypeGuard

from . import client

PROCESS_IMAGE = "LYNX.exe"


def _candidate_exes() -> list[Path]:
    """Übliche Installationsorte — nur aus OS-Variablen, ohne feste Laufwerksbuchstaben.

    Per-User-Installer landen unter %LOCALAPPDATA%\\Programs, systemweite unter
    %ProgramFiles%; LYNX installiert beides nach <base>\\LYNX\\LYNX.exe.
    """
    cands = []
    for var in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(var)
        if base:
            cands.append(Path(base) / "LYNX" / "LYNX.exe")
            cands.append(Path(base) / "Programs" / "LYNX" / "LYNX.exe")
    return cands


def _data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "lynx-mcp"


def _state_file() -> Path:
    return _data_dir() / "testhost.json"


def _log_file() -> Path:
    return _data_dir() / "lynx-run.log"


def _read_state() -> dict[str, Any] | None:
    try:
        state = json.loads(_state_file().read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_state(state: dict[str, Any]) -> None:
    _data_dir().mkdir(parents=True, exist_ok=True)
    _state_file().write_text(json.dumps(state, indent=2), encoding="utf-8")


def _clear_state() -> None:
    _state_file().unlink(missing_ok=True)


def _exe_path(cli_value: str | None = None) -> Path | None:
    """LYNX.exe-Auflösung: --exe > Env LYNX_EXE > State-Datei > Installationsorte."""
    if cli_value:
        return Path(cli_value)
    env = os.environ.get("LYNX_EXE")
    if env:
        return Path(env)
    state = _read_state()
    if state and state.get("exe"):
        return Path(state["exe"])
    return next((c for c in _candidate_exes() if c.is_file()), None)


def _process_image(pid: int) -> str | None:
    """Bildname des Prozesses (Windows: tasklist), None falls tot/unbekannt."""
    return client.process_image(pid)


def _is_our_instance(state: dict[str, Any] | None) -> TypeGuard[dict[str, Any]]:
    """Living proof: aufzeichnete PID läuft noch UND ist dasselbe LYNX.exe."""
    if not state or not state.get("pid"):
        return False
    pid = int(state["pid"])
    image = _process_image(pid)
    expected = Path(state.get("exe", PROCESS_IMAGE)).name.lower()
    return image is not None and image.lower() == expected.lower()


def _wait_ready(timeout: float, expect_pid: int | None = None) -> dict[str, Any] | None:
    """Wartet auf eine frische Discovery-Datei; None bei Timeout.

    Eine liegengebliebene (verwaiste) Datei von einem früheren Run wird nicht
    akzeptiert: Ihre Listener-pid muss uns gehören oder ein lebender Prozess sein.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            info = client.load_discovery(client.default_discovery_path())
        except client.DiscoveryError:
            info = None
        if info is not None:
            lpid = info.get("pid")
            if expect_pid is None or lpid == expect_pid:
                return info
            if lpid and _process_image(int(lpid)) is not None:
                return info  # fremde, aber lebende Instanz
        time.sleep(0.25)
    return None


# --- Befehle ---------------------------------------------------------------

def cmd_start(args: argparse.Namespace) -> int:
    state = _read_state()
    if _is_our_instance(state):
        print(f"LYNX läuft bereits (PID {state['pid']}, von testhost gestartet).")
        return 0

    exe = _exe_path(args.exe)
    if exe is None:
        print("FEHLER: LYNX.exe nicht auffindbar — Pfad über Env LYNX_EXE oder "
              "--exe setzen (geprüft wurden %LOCALAPPDATA%/%ProgramFiles% unter "
              "LYNX[/Programs]).", file=sys.stderr)
        return 1
    if not exe.is_file():
        print(f"FEHLER: LYNX.exe nicht gefunden: {exe}", file=sys.stderr)
        print("Pfad mit --exe oder Env LYNX_EXE setzen.", file=sys.stderr)
        return 1

    env = dict(os.environ, LYNX_CONTROL_ENABLED="1")
    argv = [str(exe)]
    if args.projekt:
        argv.append(str(args.projekt))
    _data_dir().mkdir(parents=True, exist_ok=True)
    with _log_file().open("ab") as log:
        flags = 0
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:  # pragma: no cover
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(
            argv, env=env, cwd=str(exe.parent),
            stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=flags, **kwargs,
        )
    _write_state({"pid": proc.pid, "exe": str(exe), "started": time.time()})
    print(f"LYNX gestartet (PID {proc.pid}), Remote Control via "
          f"LYNX_CONTROL_ENABLED=1 erzwungen. Log: {_log_file()}")
    if args.no_wait:
        return 0
    info = _wait_ready(args.timeout, expect_pid=proc.pid)
    if info is None:
        print(f"WARNUNG: Discovery-Datei nicht erschienen nach {args.timeout}s — "
              "läuft der Remote-Control-Listener? (testhost status)", file=sys.stderr)
        return 1
    match = "stimmt überein" if info.get("pid") == proc.pid else "ACHTUNG: abweicht"
    print(f"Bereit: Discovery {info['protocol']}, Port {info['port']}, "
          f"Listener-pid {info['pid']} ({match} mit {proc.pid}).")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    state = _read_state()
    if state is None:
        print("Keine von testhost gestartete Instanz bekannt (nichts zu tun).")
        return 0
    pid = int(state["pid"])
    if not _is_our_instance(state):
        print(f"State-Datei nennt PID {pid}, aber dort läuft kein (mehr) unser "
              "LYNX-Prozess — State verworfen, kein Prozess beendet.")
        _clear_state()
        return 0

    graceful = ["taskkill", "/PID", str(pid)]
    if not args.force:
        subprocess.run(graceful, capture_output=True, check=False)
    else:
        subprocess.run(graceful + ["/F"], capture_output=True, check=False)

    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        if _process_image(pid) is None:
            break
        time.sleep(0.25)
    else:
        # Graceful kam nicht durch (z. B. Dialog) -> harter Schnitt.
        subprocess.run(graceful + ["/F"], capture_output=True, check=False)
        time.sleep(0.5)
    gone = _process_image(pid) is None
    _clear_state()
    print(f"LYNX (PID {pid}) {'beendet.' if gone else 'Beenden unklar — bitte prüfen.'}")
    return 0 if gone else 1


def cmd_status(args: argparse.Namespace) -> int:
    state = _read_state()
    running = _is_our_instance(state)
    print(f"State-Datei : {_state_file()}")
    if state is None:
        print("testhost    : keine eigene Instanz aufgezeichnet")
    else:
        alive = "läuft" if running else "nicht mehr aktiv"
        print(f"testhost    : PID {state['pid']} ({alive}), exe={state.get('exe')}")
    exe = _exe_path()
    exe_word = (f"{exe} ({'gefunden' if exe.is_file() else 'FEHLT'})"
                if exe else "nicht gefunden (Env LYNX_EXE oder --exe setzen)")
    print(f"LYNX.exe    : {exe_word}")
    disc = client.default_discovery_path()
    print(f"Discovery   : {disc}")
    try:
        info = client.load_discovery(disc)
        listener_alive = info.get("pid") and _process_image(int(info["pid"])) is not None
        state_word = "LYNX Remote Control aktiv." if listener_alive \
            else "ACHTUNG: verwaiste Discovery-Datei (Listener-pid lebt nicht)."
        print(f"              Protokoll {info['protocol']}, Port {info['port']}, "
              f"Listener-pid {info['pid']} — {state_word}")
    except client.DiscoveryError as exc:
        print(f"              nicht verfügbar: {exc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lynx_mcp.testhost",
        description="LYNX.exe für Tests starten/beenden (Remote Control via "
                    "LYNX_CONTROL_ENABLED=1).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start", help="LYNX detached starten und auf Discovery warten")
    p_start.add_argument("--exe",
                         help="Pfad zu LYNX.exe (Default: Env LYNX_EXE, sonst Suche "
                              "in den Installationsorten)")
    p_start.add_argument("--projekt", metavar="DATEI",
                         help="Projektdatei beim Start öffnen (Best-Effort)")
    p_start.add_argument("--no-wait", action="store_true",
                         help="nicht auf die Discovery-Datei warten")
    p_start.add_argument("--timeout", type=float, default=30.0,
                         help="Wartezeit auf Discovery in Sekunden (Default 30)")
    p_start.set_defaults(func=cmd_start)

    p_stop = sub.add_parser("stop", help="die von testhost gestartete Instanz beenden")
    p_stop.add_argument("--force", action="store_true",
                        help="sofort hart beenden (ohne Schließen-Signal)")
    p_stop.add_argument("--timeout", type=float, default=15.0,
                        help="Gnadenfrist vor hartem Schnitt in Sekunden (Default 15)")
    p_stop.set_defaults(func=cmd_stop)

    p_status = sub.add_parser("status", help="Instanz-, exe- und Discovery-Lage zeigen")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
