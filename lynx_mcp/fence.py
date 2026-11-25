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
    control_epoch: str | None = None
    revision: int | None = None
    document_hash: str | None = None
    snapshot_id: str | None = None      # aktiver, noch gültiger project.read-Snapshot

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

    def observe_snapshot(self, meta: dict) -> None:
        """Merkte snapshotId/documentHash + Triple aus project.read (für Writes)."""
        self.observe(
            project_id=meta.get("projectId"),
            control_epoch=meta.get("controlEpoch"),
            revision=meta.get("revision"),
            document_hash=meta.get("documentHash"),
            snapshot_id=meta.get("snapshotId"),
        )

    def take_snapshot(self) -> dict | None:
        """snapshotId/documentHash für project.edit; einmalig, dann invalidiert.

        Jede Change-Transaktion invalidiert alte Snapshots (Doku) — ein
        zweiter Write ohne neuen Read wird so hart vom Server abgewehrt.
        """
        if not self.state.snapshot_id:
            return None
        snap = {"snapshotId": self.state.snapshot_id,
                "expectedDocumentHash": self.state.document_hash}
        self.state.snapshot_id = None
        self.state.document_hash = None
        return snap

    def mark_stale(self, reason: str) -> None:
        self.stale_reason = reason
        self.state.snapshot_id = None  # geändertes Projekt invalidiert Snapshots

    def require_fresh(self, intent: str) -> None:
        """Raises StaleFenceError ohne frischen Zustand oder wenn als stale markiert.

        Ein `changed`/`gap`-Ereignis hinterlässt zwar noch ein Triple, aber wir
        wissen, dass es nicht mehr verlässlich ist — erst neu lesen (PLAN §2).
        """
        if not self.state.fresh:
            raise StaleFenceError(
                f"{intent} benötigt einen frischen Projektzustand: "
                "zuerst lynx_status oder lynx_read (scope=summary) aufrufen."
                + (f" (Grund: {self.stale_reason})" if self.stale_reason else "")
            )
        if self.stale_reason:
            raise StaleFenceError(
                f"{intent} wurde nach einer Zustandsänderung blockiert "
                f"(Grund: {self.stale_reason}) — erst lynx_status oder "
                "lynx_read (scope=summary), dann neu planen."
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
