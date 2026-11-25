"""lynx-mcp — MCP-Server (stdio) für die LYNX-SHARE `lynx-control/1`-API.

Siehe PLAN.md für Architektur, Tool-Oberfläche und Meilensteine.
"""

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

try:
    __version__ = version("lynx-mcp")
except PackageNotFoundError:  # läuft direkt aus dem Repo ohne Installation
    __version__ = "0.0.1"
