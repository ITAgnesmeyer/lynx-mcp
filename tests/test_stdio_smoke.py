"""Integrationstest: echtes lynx-mcp serve über stdio (MCP-Handshake + Tools).

Der Server wird als Subprozess gestartet; sequentielles Senden/Empfängt
vermeidet das Race gegen den EOF-Shutdown (ein echter MCP-Client hält die
Verbindung offen).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="MCP-SDK erforderlich für den Stdio-Smoke")


def _send(proc, msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()


def _recv(proc, expect_id, timeout=30.0):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            pytest.fail(f"EOF vor Antwort auf id={expect_id}")
        if line.strip():
            d = json.loads(line)
            if d.get("id") == expect_id:
                return d
    pytest.fail(f"Timeout auf Antwort id={expect_id}")


def test_stdio_handshake_and_tools(tmp_path):
    # Isolierte Discovery-Datei: Test hängt nicht an einer laufenden LYNX-Instanz.
    discovery = tmp_path / "connection.json"
    discovery.write_text('{"protocol": "lynx-control/1"}')

    proc = subprocess.Popen(
        [sys.executable, "-m", "lynx_mcp", "--discovery", str(discovery), "serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    try:
        _send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        })
        init = _recv(proc, 1)
        assert init["result"]["serverInfo"]["name"] == "lynx-mcp"

        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = {t["name"] for t in _recv(proc, 2)["result"]["tools"]}
        assert {"lynx_describe", "lynx_status"} <= tools

        # Lynx-Instanz laeuft hier nicht: Tools muessen freundlich statt Crash antworten.
        _send(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {"name": "lynx_status", "arguments": {}}})
        call = _recv(proc, 3)
        assert not call["result"].get("isError")
        payload = call["result"]["structuredContent"]
        assert payload.get("error") in {"not_implemented", "not_running"}
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()
