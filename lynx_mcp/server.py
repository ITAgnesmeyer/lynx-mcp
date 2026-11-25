"""MCP-Tool-Fläche (stdio) — Tool-Menge aus PLAN.md §3.

Status: v1-Gerüst. Tools werden nach und nach je Meilenstein freigeschaltet
(read-only in M3, schreiben in M4, Patch in M5).

Wichtig: stdout gehört dem MCP-Protokoll. Jegliche Diagnostik nach stderr.
Das Token aus der Discovery-Datei darf in keiner Tool-Ausgabe, keinem Log und
keinem Schema auftauchen.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__, client, fence, summarize

# Eine MCP-Session = ein Prozess; das Fence-Gedächtnis lebt prozesslang.
_fence = fence.Fence()

mcp = MCPServer("lynx-mcp", version=__version__)


def run(discovery_path: Path | None = None) -> None:
    """Startet den MCP-Server über stdio (blockierend)."""
    # Discovery-Pfad optional vorkonfigurieren; Tools prüfen lazily beim Aufruf.
    if discovery_path is not None:
        _configure_discovery(discovery_path)
    mcp.run(transport="stdio")


_config = {"discovery": None}


def _configure_discovery(path: Path) -> None:
    _config["discovery"] = path


def _client() -> client.LynxClient:
    return client.LynxClient(_config["discovery"])


# --- Read-only Tools (M3) -------------------------------------------------

@mcp.tool()
def lynx_describe() -> dict[str, Any]:
    """Liste der vom laufenden LYNX-Build unterstützten Ops/Capabilities.

    Quelle ist `api.describe`. Der Server startet auch ohne laufende Instanz
    und meldet dann einen lesbaren Status statt eines Absturzes.
    """
    return _safe_call("api.describe")


@mcp.tool()
def lynx_status() -> dict[str, Any]:
    """Identität, revision, Tempo, Meter, Transport, Position, Pattern, Counts."""
    result = _safe_call("status")
    if "projectId" in result:
        _fence.observe(
            project_id=result["projectId"],
            control_epoch=result.get("controlEpoch"),
            revision=result.get("revision"),
        )
    return result


def _safe_call(op: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Führt eine (idempotente) Read-Op aus; Fehler als lesbare Texte statt Tracebacks."""
    try:
        return _client().call(op, params)
    except client.DiscoveryError as exc:
        return {"error": "not_running", "detail": str(exc)}
    except NotImplementedError as exc:
        return {"error": "not_implemented", "detail": str(exc)}
    except Exception as exc:  # Fehler-Mapping auf lesbare Texte (kein Token-Leak)
        return {"error": exc.__class__.__name__, "detail": str(exc)}


# Weitere Tools (lynx_changes/read/snapshot/patch/pattern_*/notes_replace/
# param_set/transport/history/device_state/catalog) folgen gemäß §3 und M3–M5.
