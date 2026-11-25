"""Session-Fence: gemerkte (projectId, controlEpoch, revision) und Snapshots.

Regeln aus PLAN.md §2/§4:
- Schreib-Tools verweigern ohne frischen Read-Zustand mit klarer Anweisung
  ("erst lynx_read/lynx_status aufrufen").
- `changed`-Fehler von LYNX markieren den Cache als stale.
- Fence-Felder werden serverseitig eingesetzt; vom Modell mitgeschickte
  Werte werden ignoriert.
- `gap: true` bei changes -> Re-Read erzwingen.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FenceState:
    project_id: str | None = None
    control_epoch: int | None = None
    revision: int | None = None
    document_hash: str | None = None

    @property
    def fresh(self) -> bool:
        return None not in (self.project_id, self.control_epoch, self.revision)


class Fence:
    """In-Memory-Gedächtnis einer MCP-Session (kein persistenter Cache)."""

    def __init__(self) -> None:
        self.state = FenceState()
        self.stale_reason: str | None = None

    def observe(self, **fields) -> None:
        """Frischt beobachtete Felder aus einer Read-/Status-Antwort auf."""
        for key, value in fields.items():
            if value is not None and hasattr(self.state, key):
                setattr(self.state, key, value)
        self.stale_reason = None

    def mark_stale(self, reason: str) -> None:
        self.stale_reason = reason

    def require_fresh(self, intent: str) -> None:
        """Raises StaleFenceError, falls Schreiboperation ohne frischen Zustand."""
        if not self.state.fresh:
            raise StaleFenceError(
                f"{intent} benötigt einen frischen Projektzustand: "
                "zuerst lynx_status oder lynx_read (scope=summary) aufrufen."
                + (f" (Grund: {self.stale_reason})" if self.stale_reason else "")
            )

    def fence_params(self) -> dict[str, int | str]:
        """Fence-Felder für eine Write-Op; nur aufrufen nach require_fresh()."""
        return {
            "projectId": self.state.project_id,
            "controlEpoch": self.state.control_epoch,
            "revision": self.state.revision,
        }


class StaleFenceError(RuntimeError):
    pass
