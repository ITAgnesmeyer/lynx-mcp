"""Projekt-JSON → Kurzstruktur für kontextsparsame Reads (PLAN.md §2.3).

`summarize()` reduziert ein Ergebnis von `project.read` auf Top-Level-Ebene:
Tempo/Meter, Zählungen + Namen/UIDs großer Sammlungen (patterns, channels,
mixer, playlist/Arrangements, Automationen) und Referenzpfade für Folgereads
(`/patterns/3/notes/…`). Vollständige Seiten gibt nur `lynx_snapshot` auf Disk.

Das native Format variiert mit dem Build — deshalb erkennt die Funktion
Sammlungen heuristisch (Liste von Objekten) statt auf starre Schlüssel zu
setzen; `api.describe`/`status` bleiben die Autorität für Einzelfelder.
"""

from __future__ import annotations

import hashlib
from typing import Any

MAX_NOTE_WARN = 2000   # Warnung bei > 2000 Notes pro pattern (§7 Risiko)
MAX_SAMPLES = 12       # Namen, die pro Sammlung gezeigt werden


def document_hash(payload: bytes | str) -> str:
    """Byte-Hash über die Read-Antwort (SHA-256, wie documentHash der Doku)."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _entry_name(item: Any) -> Any:
    if isinstance(item, dict):
        return item.get("name") or item.get("title") or item.get("label")
    return None


def _note_count(items: list) -> int:
    total = 0
    for it in items:
        if isinstance(it, dict):
            for key in ("notes", "events"):
                v = it.get(key)
                if isinstance(v, list):
                    total = max(total, len(v))
    return total


def summarize(project: dict[str, Any]) -> dict[str, Any]:
    """Kurzdarstellung eines Projekt-Baums; Detailpfade statt Vollausgabe."""
    out: dict[str, Any] = {"collections": {}, "notesLarge": False}
    if not isinstance(project, dict):
        raise TypeError("summarize erwartet ein JSON-Objekt")
    for key in ("bpm", "tempo"):
        if key in project:
            out["tempo"] = {key: project[key]}
    if isinstance(project.get("meter"), dict):
        out["meter"] = project["meter"]
    for key, value in project.items():
        if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            names = [_entry_name(v) for v in value[:MAX_SAMPLES]]
            notes = _note_count(value) if key in ("patterns", "pattern") else 0
            if notes > MAX_NOTE_WARN:
                out["notesLarge"] = True
            out["collections"][key] = {
                "count": len(value),
                "names": [n for n in names if n is not None],
                "maxNotesOrEvents": notes or None,
                "readPath": f"/{key}/<index>",
            }
        elif isinstance(value, dict):
            out.setdefault("objects", {})[key] = sorted(value.keys())[:20]
    return out
