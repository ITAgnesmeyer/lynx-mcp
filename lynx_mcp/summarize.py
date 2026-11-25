"""Projekt-JSON → Kurzstruktur für kontextsparsame Reads (PLAN.md §2.3).

`summarize()` reduziert ein Voll-/Seiten-Ergebnis von `project.read` auf:
Tempo/Meter, Channel-Namen + IDs, Pattern-Liste (Name, Länge, Notencount),
Arrangements, Mixer-Tracks, Automationen — jeweils mit Stable-IDs und
Referenzpfaden (z. B. `/patterns/3/notes/…`) für Folgereads, plus Byte-Hash.

Große Listen (Notes) werden nur gezählt, nie ins Context gegeben; Rohe
Voll-JSON-Seiten gibt es nur auf expliziten Wunsch (`maxPages`/Cursor).
"""

from __future__ import annotations

import hashlib
from typing import Any

MAX_NOTES_WARN = 2000  # Warnung bei > 2000 Notes pro Aufruf (§7 Risiko)


def document_hash(payload: bytes | str) -> str:
    """Byte-Hash über die Read-Antwort (für Fence/Dokumentation)."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def summarize(project: dict[str, Any]) -> dict[str, Any]:
    """Kurzdarstellung eines Projekt-Baums; Detailpfade statt Vollausgabe.

    TODO(M2): echte Felder aus project.read mappen (channels, patterns,
    playlist/arrangement, mixer, automations) inkl. Notencount und Warnung
    bei > MAX_NOTES_WARN Notes.
    """
    patterns = project.get("patterns", []) if isinstance(project, dict) else []
    note_counts = [len(p.get("notes", [])) for p in patterns if isinstance(p, dict)]
    return {
        "patternCount": len(patterns),
        "tempo": project.get("tempo") if isinstance(project, dict) else None,
        "meter": project.get("meter") if isinstance(project, dict) else None,
        "totalNotes": sum(note_counts),
        "largeNoteList": any(c > MAX_NOTES_WARN for c in note_counts),
    }
