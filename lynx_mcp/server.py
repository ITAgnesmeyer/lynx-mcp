"""MCP-Tool-Fläche (stdio) — vollständige lynx-control/1-Oberfläche.

Alle 29 Ops des Build 0.1.31.1 sind abgedeckt (per Live-Probing verifiziert,
Nov 2026). Regeln aus der Protokoll-Doku, die die Tool-Schemas transportieren:
Schreiboperationen erfordern gestopptes Playback und ein frisches Fence-Tripel
(projectId/epoch/revision — wird serverseitig gesetzt, nie vom Caller);
`uncertain`-Fehler niemals automatisch wiederholen; nach strukturellem Change
immer neu lesen; Patches ändern keine Assets/Pfade/Plugin-States (Allowlist).

Token-Disziplin: Discovery wird nur im client gelesen; das Token erscheint in
keiner Antwort, keinem Log, keinem Schema. stdout gehört dem MCP-Protokoll.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__, client, fence, summarize, testhost

MAX_REPLY_CHARS = 200_000     # Tool-Antworten gekürzt (~200 KiB, PLAN §4)
SUMMARY_PAGES = 16            # <= 16 Seiten à 32 KiB pro summary-Read
NOTE_WARN = 2000


def out_dir() -> Path:
    """Ziel für lynx_snapshot: LYNX_MCP_OUT_DIR > out/ im Repo (Dev-Checkout)
    > %LOCALAPPDATA%\\lynx-mcp\\out (installierter Lauf, z. B. via uvx — dort
    wäre das Paketverzeichnis flüchtig/schreibgeschützt)."""
    env = os.environ.get("LYNX_MCP_OUT_DIR")
    if env:
        return Path(env)
    repo = Path(__file__).resolve().parents[1]
    if (repo / "pyproject.toml").is_file():
        return repo / "out"
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "lynx-mcp" / "out"


def _dir_arg(p: str | None) -> Path:
    """Optionaler Zielordner aus einem Tool-Parameter: explizit statt
    festgeschrieben, damit Pfad-Richtlinien des Agenten hier greifen können.
    None/leer = Standard (out_dir()). Absolutpflicht, ~ wird expandiert."""
    if p is None or not str(p).strip():
        return out_dir()
    d = Path(str(p)).expanduser()
    if not d.is_absolute():
        raise ValueError("out_dir muss absolut angegeben werden "
                         "(z. B. D:\\musik\\projekt)")
    return d


def _name_arg(s: str | None) -> str | None:
    """Dateistempel ohne Pfad und ohne Endung; None = Auto-Name.
    Separatoren, '..', Kontrollzeichen und Längen > 96 sind raus."""
    if s is None or not str(s).strip():
        return None
    stem = str(s).strip()
    if ".." in stem or re.search(r'[\\/:*?"<>|\x00-\x1f]', stem) \
            or len(stem) > 96:
        raise ValueError("filename nur als reiner Name ohne Pfad "
                         "(max 96 Zeichen)")
    return stem

_fence = fence.Fence()
_client: client.LynxClient | None = None

mcp = MCPServer("lynx-mcp", version=__version__)


def run(discovery_path: Path | None = None) -> None:
    """Startet den MCP-Server über stdio (blockierend)."""
    global _client
    if discovery_path is not None:
        _client = client.LynxClient(discovery_path)
    mcp.run(transport="stdio")


def _lynx() -> client.LynxClient:
    global _client
    if _client is None:
        _client = client.LynxClient()
    return _client


# --- Fehler-Mapping (lesbar, ohne Token) --------------------------------------

def _fail(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, client.LynxError):
        if exc.code == "changed":
            _fence.mark_stale("changed")
            detail = (f"{exc}. Projekt hat sich seit dem letzten Read geändert — "
                      "Zustand mit lynx_status oder lynx_read (scope=summary) "
                      "erneuern, dann neu planen.")
        elif exc.code == "busy":
            detail = (f"{exc}. LYNX ist beschäftigt (Playback/Aufnahme?) — "
                      "lynx_transport action=stop oder abwarten.")
        else:
            detail = str(exc)
        return {"error": exc.code, "detail": detail, "uncertain": exc.uncertain}
    if isinstance(exc, client.DiscoveryError):
        return {"error": "not_running", "detail": str(exc)}
    if isinstance(exc, client.ProtocolError):
        return {"error": "protocol", "detail": str(exc)}
    return {"error": exc.__class__.__name__, "detail": str(exc)}


def _read(op: str, args: dict | None = None) -> Any:
    """Read-Op; frische Fence-Felder aus der Antwort werden beobachtet.

    Read-Ops lehnen expected*-Felder ab ('Unknown field') — hier nie mitsenden.
    """
    try:
        result = _lynx().request(op, args)
        _fence.observe(project_id=result.get("projectId"),
                       control_epoch=result.get("controlEpoch"),
                       revision=result.get("revision"))
        return _cap(result)
    except Exception as exc:
        return _fail(exc)


def _write(op: str, args: dict, snapshot: bool = False) -> Any:
    """Schreib-Op mit serverseitig gesetzten Fence-Feldern (Read-before-Write)."""
    try:
        _fence.require_fresh(op)
        guarded = dict(args)
        guarded.update({
            "expectedProjectId": _fence.state.project_id,
            "expectedEpoch": _fence.state.control_epoch,
            "expectedRevision": _fence.state.revision,
        })
        if snapshot:
            snap = _fence.take_snapshot()
            if snap is None:
                return {"error": "no_snapshot",
                        "detail": "project.edit braucht einen frischen Vollread: "
                                  "zuerst lynx_read scope=summary oder lynx_snapshot."}
            guarded.update(snap)
        result = _lynx().request(op, guarded)
        _fence.observe(project_id=result.get("projectId"),
                       control_epoch=result.get("controlEpoch"),
                       revision=result.get("revision"))
        # Snapshots sind nach jedem Write verbraucht (jede Change-Transaktion
        # invalidiert alte Snapshots); observe() ignoriert None, also explizit.
        _fence.state.snapshot_id = None
        _fence.state.document_hash = None
        return _cap(result)
    except fence.StaleFenceError as exc:
        return {"error": "stale_fence", "detail": str(exc)}
    except Exception as exc:
        return _fail(exc)


def _cap(obj: Any) -> Any:
    """Antworten auf ~200 KiB begrenzen, sonst Kontext-Flut (PLAN §4)."""
    try:
        text = json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return obj
    if len(text) <= MAX_REPLY_CHARS:
        return obj
    return {"truncated": True, "sizeBytes": len(text.encode("utf-8")),
            "hint": "Antwort zu groß für den Kontext — lynx_snapshot schreibt das "
                    "Komplette auf Disk, oder paginiert lesen (offset/limit)."}


def _clean(**pairs: Any) -> dict[str, Any]:
    """Args-Dict ohne None-Werte (LYNX meldet 'Unknown field' bei null-Fields)."""
    return {k: v for k, v in pairs.items() if v is not None}


# --- Observieren ---------------------------------------------------------------

@mcp.tool()
def lynx_describe() -> dict[str, Any]:
    """Ops/Capabilities/Limits dieser Instanz (api.describe).

    Autoritative Quelle dafür, welche Ops dieser Build hat. Funktioniert ohne
    laufendes LYNX mit freundlichem 'not_running'-Status."""
    return _read("api.describe")


@mcp.tool()
def lynx_status() -> dict[str, Any]:
    """Identität, revision, Tempo, Meter, Transport, Position, Counts (status).

    Günstigster Weg, das Fence (projectId/epoch/revision) aufzufrischen —
    vor jedem Write-Plan zuerst hiermit oder lynx_read den Zustand prüfen."""
    return _read("status")


@mcp.tool()
def lynx_session() -> dict[str, Any]:
    """Bounded Übersicht: Projektname/pfad, Channels, Mixer, Patterns,
    Playlist-Clips, Transport, canUndo/canRedo (session.inspect).

    Deutlich billiger als ein Vollread; Channels/Mixer-Einträge liefern die
    index-Werte für die .set-Tools."""
    return _read("session.inspect")


@mcp.tool()
def lynx_changes(from_revision: int | None = None, limit: int | None = None) -> dict[str, Any]:
    """Bounded Polling-Feed von Revisionsänderungen, max 128 (changes).

    gap:true heißt: Änderungen außerhalb des Puffers — vor weiteren
    Schlüssen Vollread (lynx_read scope=summary). Kein Push-Abo."""
    if from_revision is None:
        if _fence.state.revision is None:
            return {"error": "stale_fence",
                    "detail": "Ohne from_revision braucht es einen bekannten "
                              "Zustand: erst lynx_status aufrufen."}
        from_revision = _fence.state.revision
    result = _read("changes", _clean(fromRevision=from_revision,
                                     limit=min(int(limit), 128) if limit else None))
    if isinstance(result, dict) and result.get("gap"):
        _fence.mark_stale("changes-gap")
        result = dict(result, hint="gap — Vollread nötig (lynx_read scope=summary)")
    return result


@mcp.tool()
def lynx_device_state() -> dict[str, Any]:
    """deviceStateHash über Channel-/Mixer-/Nested-Geräte-State (device.state).

    Vendor-GUIs können opaque State ohne Revision ändern — zusätzlich zu
    revisions prüfen. Erfordert gestopptes Playback/Recording."""
    return _read("device.state")


# --- Lesen -----------------------------------------------------------------------

@mcp.tool()
def lynx_read(scope: str = "summary", pattern_index: int | None = None,
              pattern_id: str | None = None, offset: int | None = None,
              limit: int | None = None) -> dict[str, Any]:
    """Projektzustand kontextsparsam lesen.

    scope=summary (Default): interner Vollread, Kurzfassung + Fence fürs
    Write-Gedächtnis. pattern_notes: paginierte Notes (vor replace_notes
    immer ALLE leerend lesen!). playlist: Clips/Tracks einer Anordnung.
    Rohe Voll-JSON-Seiten gibt bewusst nur lynx_snapshot auf Disk."""
    try:
        if scope == "summary":
            project, meta = _lynx().project_read_full(max_pages=SUMMARY_PAGES)
            _fence.observe_snapshot(meta)
            out = summarize.summarize(project)
            out["fence"] = {k: meta[k] for k in
                            ("projectId", "controlEpoch", "revision")}
            return out
        if scope == "pattern_notes":
            return _read("pattern.notes",
                         _clean(index=pattern_index, patternId=pattern_id,
                                offset=offset, limit=limit))
        if scope == "playlist":
            return _read("playlist.inspect", _clean(offset=offset, limit=limit))
        if scope == "session":
            return _read("session.inspect")
        return {"error": "invalid",
                "detail": f"unbekannter scope {scope!r} "
                          "(summary|pattern_notes|playlist|session)"}
    except Exception as exc:
        return _fail(exc)


@mcp.tool()
def lynx_snapshot(max_pages: int = 2048,
                  out_dir: str | None = None) -> dict[str, Any]:
    """Komplettes Projekt-JSON auf Disk statt in den Kontext.

    Ziel: out_dir (absolut, ~ erlaubt) oder Standard — Env LYNX_MCP_OUT_DIR,
    sonst out/ neben dem Repo (Dev) bzw. %LOCALAPPDATA%\\lynx-mcp\\out.
    Expliziter Zielordner statt festgeschriebener Pfade, damit
    Agenten-Richtlinien den Schreibpfad prüfen können. Gibt Pfad +
    documentHash + Fence zurück; Basis für große lynx_patch-Pläne.
    Erfordert gestopptes Playback; Snapshot max 64 MiB, 4 behaltene Snapshots."""
    try:
        odir = _dir_arg(out_dir)
    except ValueError as exc:
        return {"error": "invalid", "detail": str(exc)}
    try:
        project, meta = _lynx().project_read_full(
            max_pages=max_pages, page_limit=65536)
        _fence.observe_snapshot(meta)
        odir.mkdir(parents=True, exist_ok=True)
        path = odir / f"snapshot-{meta['projectId']}-r{meta['revision']}.json"
        path.write_text(json.dumps(project, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        return {"path": str(path), "bytes": path.stat().st_size,
                "documentHash": meta["documentHash"],
                "revision": meta["revision"],
                "hint": "Patch gegen dieses snapshot planen (lynx_patch)."}
    except Exception as exc:
        return _fail(exc)


@mcp.tool()
def lynx_catalog(kind: str, offset: int = 0, limit: int | None = None) -> dict[str, Any]:
    """Instrument-/Effekt-Kataloge (instrument.catalog | effect.catalog).

    IDs sind opaque Strings ('lynx:gen:Kick', 'native:0', 'plugin:VST-…') und
    werden channel.create / instrument.replace / effect.load übergeben.
    Paginiert über offset; count = Gesamtzahl."""
    op = {"instruments": "instrument.catalog", "effects": "effect.catalog"}.get(kind)
    if op is None:
        return {"error": "invalid", "detail": "kind: instruments|effects"}
    return _read(op, _clean(offset=offset, limit=limit))


@mcp.tool()
def lynx_plugin_inspect(target: dict | None = None) -> dict[str, Any]:
    """Hosted-Parameter lesend (plugin.inspect): ohne target alle Geräte,
    mit target {kind:'instrument',channelIndex} oder
    {kind:'effect',mixerIndex,effectIndex} die Parameter einzeln.

    Werte sind normalisiert 0..1; displayValue/label nennen die Natubeinheiten.
    target liefert exakt die Struktur für lynx_plugin_parameters."""
    return _read("plugin.inspect", target and {"target": target} or {})


# --- Dokument-Patch ----------------------------------------------------------------

@mcp.tool()
def lynx_patch(patch: list[dict]) -> dict[str, Any]:
    """Atomare Projekt-Änderung via JSON Patch (RFC 6902, 1–128 Ops) = EIN Undo.

    Nur test/add/replace/remove; Paths als JSON Pointer. Fence und
    snapshotId/documentHash werden serverseitig aus dem letzten Vollread
    gesetzt ( erst lynx_read scope=summary oder lynx_snapshot!).
    Arrays/Referenzen sind literal — abhängige Indizes in derselben
    Transaktion führen; für Struktur-Actions die typisierten Tools vorziehen.
    Assets/Pfade/Plugin-States sind schreibgeschützt (Allowlist).
    Nach Erfolg immer neu lesen."""
    if not (1 <= len(patch) <= 128):
        return {"error": "invalid", "detail": "patch braucht 1–128 Ops"}
    return _write("project.edit", {"patch": patch}, snapshot=True)


# --- Typisierte Schreib-Tools -------------------------------------------------------

@mcp.tool()
def lynx_tempo_set(bpm: float) -> dict[str, Any]:
    """Song-Tempo in BPM setzen (tempo.set). Gleicher Wert = No-op ohne Undo."""
    return _write("tempo.set", {"bpm": float(bpm)})


@mcp.tool()
def lynx_pattern_create(index: int | None = None, name: str | None = None,
                        length_ticks: int | None = None) -> dict[str, Any]:
    """Neues Pattern anlegen (pattern.create): append oder an index 0..count.

    name defaultet auf 'Pattern N'; lengthTicks 0 = folgt den Notes.
    Ergebnis: index/patternId/name/lengthTicks/patternCount — Index-Felder
    für Folge-Tools liefern."""
    return _write("pattern.create", _clean(index=index, name=name,
                                           lengthTicks=length_ticks))


@mcp.tool()
def lynx_pattern_clone(index: int, name: str | None = None) -> dict[str, Any]:
    """Kopie eines Patterns direkt danach (pattern.clone).

    Notes, Expression, Events, Marker, Loops und Farbe bleiben erhalten;
    neue Pattern-ID. Original existieren muss (index aus lynx_session)."""
    return _write("pattern.clone", _clean(index=index, name=name))


@mcp.tool()
def lynx_pattern_set(index: int, name: str | None = None,
                     length_ticks: int | None = None) -> dict[str, Any]:
    """Name und/oder lengthTicks eines Patterns setzen (pattern.set).

    lengthTicks: 0 (folgen den Notes) oder ganzzahlige Vielfache von Takten
    (barTicks aus lynx_status × 1..999). No-op erzeugt kein Undo.
    Löschen ist keine typisierte Op — dafür lynx_patch."""
    return _write("pattern.set", _clean(index=index, name=name,
                                        lengthTicks=length_ticks))


@mcp.tool()
def lynx_notes_replace(pattern_index: int | None = None, pattern_id: str | None = None,
                       notes: list[dict] | None = None) -> dict[str, Any]:
    """Notes eines Patterns VOLLSTÄNDIG ersetzen (pattern.replace_notes).

    Vorbedingung aus der Doku: ZUERST alle Notes mit
    lynx_read(scope=pattern_notes) leerend lesen und alle 18 Felder (auch
    expression/chanceOne) übernehmen — sonst gehen MPE-Kurven verloren.
    expression: {pitch|timbre|pressure: [[tick, wert], …}] alle drei Lanes
    Pflicht (leeres Array = keine). > 2000 Notes: lieber lynx_patch."""
    if not notes:
        return {"error": "invalid", "detail": "notes (vollständige Liste) fehlt"}
    if len(notes) > NOTE_WARN:
        return {"error": "limit",
                "detail": f"{len(notes)} Notes über Kontext-Richtwert {NOTE_WARN} — "
                          "Einzelnutzung von lynx_patch empfohlen"}
    return _write("pattern.replace_notes",
                   _clean(index=pattern_index, patternId=pattern_id, notes=notes))


@mcp.tool()
def lynx_channel_create(instrument_id: str, name: str | None = None,
                        mixer_index: int | None = None) -> dict[str, Any]:
    """Neuen Channel mit Instrument anlegen (channel.create).

    instrument_id aus lynx_catalog('instruments'). Name defaultet auf das
    Instrument; mixer_index wählt den Mixer-Slot. Ergebnis: channelIndex +
    mixerIndex — Basis für plugin-Parameter-Zugriffe."""
    return _write("channel.create", _clean(instrumentId=instrument_id,
                                           name=name, mixerIndex=mixer_index))


@mcp.tool()
def lynx_channel_set(index: int, name: str | None = None, volume: float | None = None,
                     pan: float | None = None, muted: bool | None = None) -> dict[str, Any]:
    """Channel-Eigenschaften setzen (channel.set): name/volume/pan/muted.

    Mindestens ein Control; nicht Angegebenes bleibt. solo gibt es hier nicht
    (nur im Mixer). volume 0..~1.26, pan -1..1 (normalisiert)."""
    args = _clean(index=index, name=name, volume=volume, pan=pan, muted=muted)
    if len(args) == 1:
        return {"error": "invalid",
                "detail": "Mindestens ein Control (name/volume/pan/muted) angeben."}
    return _write("channel.set", args)


@mcp.tool()
def lynx_mixer_set(index: int, volume: float | None = None, pan: float | None = None,
                   muted: bool | None = None, solo: bool | None = None) -> dict[str, Any]:
    """Mixer-Track/Setzung steuern (mixer.set): volume/pan/muted/solo.

    index aus lynx_session (mixer-Liste; 0 = Master). Mindestens ein Control."""
    args = _clean(index=index, volume=volume, pan=pan, muted=muted, solo=solo)
    if len(args) == 1:
        return {"error": "invalid",
                "detail": "Mindestens ein Control (volume/pan/muted/solo) angeben."}
    return _write("mixer.set", args)


@mcp.tool()
def lynx_instrument_replace(channel_index: int, instrument_id: str) -> dict[str, Any]:
    """Instrument eines Channels gegen frische Instanz tauschen
    (instrument.replace). instrument_id aus lynx_catalog('instruments').
    Opaque States des alten Geräts gehen bewusst verloren."""
    return _write("instrument.replace",
                  {"channelIndex": channel_index, "instrumentId": instrument_id})


@mcp.tool()
def lynx_effect_load(mixer_index: int, effect_id: str,
                     effect_index: int | None = None) -> dict[str, Any]:
    """Effekt auf einen Mixer-Track laden (effect.load).

    effect_id aus lynx_catalog('effects'); effect_index = Position in der
    Kette (append wenn weggelassen)."""
    return _write("effect.load", _clean(mixerIndex=mixer_index,
                                        effectId=effect_id,
                                        effectIndex=effect_index))


@mcp.tool()
def lynx_effect_remove(mixer_index: int, effect_index: int) -> dict[str, Any]:
    """Effekt aus der Kette eines Mixer-Tracks entfernen (effect.remove)."""
    return _write("effect.remove", {"mixerIndex": mixer_index,
                                    "effectIndex": effect_index})


@mcp.tool()
def lynx_plugin_parameters(target: dict, parameters: list[dict]) -> dict[str, Any]:
    """Geräteparameter setzen (plugin.parameters_set), 1–64 pro Aufruf.

    target: {kind:'instrument', channelIndex} oder
            {kind:'effect', mixerIndex, effectIndex}  — exakt so, wie
            lynx_plugin_inspect es liefert. Native Instrumente sind hier
            ausgeschlossen (nur hosted + Mixer-Effekte).
    parameters: [{index, value, expectedValue?}] mit value normalisiert 0..1;
    expectedValue (aus plugin.inspect) = Guard gegen veraltete Vendor-Werte.
    changed im Ergebnis = Anzahl gesetzter Parameter."""
    if not (1 <= len(parameters) <= 64):
        return {"error": "invalid", "detail": "parameters braucht 1–64 Einträge"}
    kind = (target or {}).get("kind")
    if kind not in ("instrument", "effect"):
        return {"error": "invalid",
                "detail": "target.kind muss 'instrument' oder 'effect' sein"}
    return _write("plugin.parameters_set", {"target": target,
                                            "parameters": parameters})


@mcp.tool()
def lynx_playlist_edit(edits: list[dict]) -> dict[str, Any]:
    """Playlist/Arrangement bearbeiten (playlist.edit), 1–128 Edits.

    Pro Edit: action 'add' (kind 'pattern'|'audio'|'automation', pattern/
    channel/automation + track/start, optional length/offset/offsetFraction/
    gain/pan/muted/fadeIn/fadeOut/reversed/pitch/stretch — clipId wird
    zugewiesen), 'update' (clipId + Felder), 'duplicate' (clipId),
    'remove' (clipId). Inhaltlich gesperrte Rows erst via
    lynx_patch lockedToContent=false, dann editieren.
    clipIds aus lynx_read(scope=playlist)."""
    if not (1 <= len(edits) <= 128):
        return {"error": "invalid", "detail": "edits braucht 1–128 Einträge"}
    return _write("playlist.edit", {"edits": edits})


# --- Transport & History --------------------------------------------------------

@mcp.tool()
def lynx_transport(action: str) -> dict[str, Any]:
    """Playback starten/stoppen: action play|stop (transport.*).

    play nutzt den aktuellen Song/Pattern-Modus; stop geht auch bei
    veraltetem Fence (dokumentiert) und bricht Aufnahme ab."""
    if action == "stop":
        args = ({"expectedProjectId": _fence.state.project_id,
                 "expectedEpoch": _fence.state.control_epoch,
                 "expectedRevision": _fence.state.revision}
                if _fence.state.fresh else {})
        try:
            result = _lynx().request("transport.stop", args)
            _fence.observe(**{k2: result.get(k1) for k1, k2 in
                              (("projectId", "project_id"),
                               ("controlEpoch", "control_epoch"),
                               ("revision", "revision"))})
            return _cap(result)
        except Exception as exc:
            return _fail(exc)
    if action == "play":
        return _write("transport.play", {})
    return {"error": "invalid", "detail": "action: play|stop"}


@mcp.tool()
def lynx_history(action: str, expected_device_state_hash: str | None = None) -> dict[str, Any]:
    """Natives undo/redo (history.*), kein per-client-selektives Rücknehmen.

    Ownership des obersten Schritts nötig — fremde UI-Schritte gehören dem
    Nutzer. canUndo/canRedo aus lynx_session prüfen.
    expectedDeviceStateHash (aus lynx_device_state): Guard gegen Restore nach
    unrelated Opaque-Device-Änderungen."""
    if action not in ("undo", "redo"):
        return {"error": "invalid", "detail": "action: undo|redo"}
    return _write(f"history.{action}",
                  _clean(expectedDeviceStateHash=expected_device_state_hash))


# --- Audio-Export (headless, ohne die laufende Instanz zu ändern) -------------

EXPORT_FORMATS = ("wav", "flac", "ogg", "mp3", "aif", "m4a")
EXPORT_TIMEOUT_MAX = 600


def _num(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _clip_crop(c: list, start: int, end: int | None) -> list | None:
    """Ein Playlist-Clip [pattern, track, start, length, offset, kind, quelle, …]
    auf den Bereich [start, end) schneiden; None = fällt ganz raus, [] = leer.
    Offset und Länge folgen dem Schnitt (audio/pattern/automation gleicher
    Ticker-Wert), wie LYNX' makeRenderSong es bei einer Selection tut."""
    if len(c) < 7 or not all(isinstance(c[i], int) for i in (2, 3, 4)):
        return None
    s, length, off = c[2], c[3], c[4]
    if length <= 0 or s + length <= start or (end is not None and s >= end):
        return []
    if s < start:
        off += start - s
        length -= start - s
        s = start
    if end is not None and s + length > end:
        length = end - s
    c = list(c)
    c[2], c[3], c[4] = s - start, length, off
    return c


def _clips_crop(items: list, start: int, end: int | None) -> list | None:
    """Clip-Liste schneiden; None, wenn ein Eintrag unerwartet geformt ist."""
    out = []
    for c in items:
        if not isinstance(c, list):
            return None
        r = _clip_crop(c, start, end)
        if r is None:
            return None
        if r:
            out.append(r)
    return out


def _crop_project(project: dict, start: int, end: int | None) -> tuple[
        dict, int | None]:
    """Snapshot-Dokument auf [start, end) beschneiden (PPQ 960). Liefert die
    beschnittene Kopie und die Zahl der Clips, die im Bereich übrig blieben
    (None = Dokumentform unbekannt → lieber unbeschnitten durchreichen)."""
    pl = project.get("playlist")
    if not isinstance(pl, list):
        return project, None
    clips = _clips_crop(pl, start, end)
    if clips is None:
        return project, None
    out = dict(project)
    out["playlist"] = clips
    arrs = project.get("arrangements")
    if isinstance(arrs, list):  # andere Arrangements mit Clips ebenso
        new_arrs = []
        for a in arrs:
            if isinstance(a, dict) and isinstance(a.get("clips"), list):
                ac = _clips_crop(a["clips"], start, end)
                if ac is None:
                    return project, None
                a = dict(a, clips=ac)
            new_arrs.append(a)
        out["arrangements"] = new_arrs
    autos = project.get("automations")
    if isinstance(autos, list) and (start or end is not None):
        new_autos = []
        for a in autos:  # Punkte: vor/nach dem Bereich fort, Ticks relativieren
            if isinstance(a, dict) and isinstance(a.get("points"), list):
                pts = []
                for pt in a["points"]:
                    if (isinstance(pt, list) and pt
                            and isinstance(pt[0], (int, float))):
                        if pt[0] < start or (end is not None
                                             and pt[0] > end):
                            continue  # (keine Rand-Interpolation, s. Docstring)
                        pt = list(pt)
                        pt[0] -= start
                    pts.append(pt)
                a = dict(a, points=pts)
            new_autos.append(a)
        out["automations"] = new_autos
    return out, len(clips)


@mcp.tool()
def lynx_export(format: str = "wav", sample_rate: int | None = None,
                timeout_s: int = 120, start_ticks: int | None = None,
                end_ticks: int | None = None, out_dir: str | None = None,
                filename: str | None = None) -> dict[str, Any]:
    """Aktuelle Session offline zu Audio rendern (lynx_export).

    Kette: project.read (Vollread) -> natives .lynx im Snapshot-Ordner ->
    LYNX.exe --export als neuer, fensterloser Prozess. Die laufende Instanz
    wird nicht geändert (der Export-Zweig verlässt LYNX' initialise vor dem
    Remote-Control-Listener); nur der Read verlangt gestopptes Playback.
    Formate: wav/flac/aif 24 bit, mp3 320 kbit/s, m4a AAC 192 kbit/s;
    sample_rate (8000–384000) wirkt nur bei wav. LYNX.exe-Pfad: Env
    LYNX_EXE, sonst Installationsuche. Ein Timeout bricht den Exportprozess
    ab — Ausgabedatei kann unvollständig sein, dann prüfen (lynx_status,
    Datei-Größe), niemals blind wiederholen. Stummer Render gilt als
    Fehler (silent:true mit Grund), die WAV-Datei existiert trotzdem.
    start_ticks/end_ticks (PPQ 960, 1 Takt 4/4 = 3840) exportieren nur
    diesen Bereich: Der Schnitt liegt im Snapshot (Playlist-Clips,
    Arrangements, Automations-Punkte — ohne Rand-Interpolation), die
    Instanz und ihre Selection bleiben unberührt; ohne end_ticks bis
    Song-Ende. Leerer Bereich → empty_range, kein Exportprozess.
    out_dir (absolut, ~ erlaubt) schreibt das Audio in diesen Ordner statt
    in den Standard-Snapshot-Ordner — Pfad richtliniengreifbar statt
    festgeschrieben; filename setzt den Namen (ohne Pfad/Endung). Nur das
    Audio landet dort, Arbeitsdateien bleiben im Arbeitsordner."""
    if format not in EXPORT_FORMATS:
        return {"error": "invalid",
                "detail": f"format: {'|'.join(EXPORT_FORMATS)}"}
    if sample_rate is not None and not 8000 <= int(sample_rate) <= 384000:
        return {"error": "invalid", "detail": "sample_rate 8000..384000"}
    try:
        target = _dir_arg(out_dir)
        custom = _name_arg(filename)
    except ValueError as exc:
        return {"error": "invalid", "detail": str(exc)}
    start = int(start_ticks or 0)
    end = None if end_ticks is None else int(end_ticks)
    if start < 0 or (end is not None and end <= start):
        return {"error": "invalid",
                "detail": "start_ticks >= 0, end_ticks > start_ticks"}
    timeout_s = max(5, min(int(timeout_s), EXPORT_TIMEOUT_MAX))
    try:
        project, meta = _lynx().project_read_full(
            max_pages=2048, page_limit=65536)
    except Exception as exc:
        return _fail(exc)
    _fence.observe_snapshot(meta)
    if start or end is not None:
        project, left = _crop_project(project, start, end)
        if left == 0:
            return {"error": "empty_range", "range": [start, end],
                    "detail": "im Bereich liegt kein Clip — Selection zu "
                              "weit vorn/hinten? (Clips: lynx_read "
                              "scope=playlist)"}
    else:
        left = None
    exe = testhost._exe_path()
    if exe is None or not exe.is_file():
        return {"error": "no_exe",
                "detail": "LYNX.exe nicht gefunden — Pfad über Env LYNX_EXE "
                          "setzen (setx LYNX_EXE \"C:\\pfad\\zu\\LYNX.exe\") "
                          "oder portable Installation: s. README"}
    work = _dir_arg(None)        # Arbeitsordner = Standard (nicht das Ziel)
    work.mkdir(parents=True, exist_ok=True)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"error": "invalid", "detail": f"out_dir nicht anlegbar: {exc}"}
    stem = f"export-{meta['projectId']}-r{meta['revision']}"
    if start or end is not None:
        stem += f"-{start}x{end if end is not None else 'e'}"
    proj_file = work / (stem + ".lynx")  # Arbeitsdatei: immer Arbeitsordner
    proj_file.write_text(json.dumps(project, ensure_ascii=False),
                         encoding="utf-8")
    out = target / ((custom or stem) + "." + format)
    args = [str(exe), "--export", str(proj_file), str(out)]
    if sample_rate is not None and format == "wav":
        args += ["--rate", str(int(sample_rate))]
    try:
        proc = subprocess.run(args, capture_output=True, text=True,
                              timeout=timeout_s, cwd=str(exe.parent),
                              check=False)  # returncode wird selbst bewertet
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "uncertain": True,
                "detail": f"Exportprozess nach {timeout_s}s abgebrochen — "
                          f"{out} kann unvollständig sein"}
    report = {}
    rtxt = Path(str(out) + ".txt")          # LYNX schreibt <ausgabe>.txt
    if rtxt.is_file():
        for line in rtxt.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, val = line.partition("=")
            if key in ("result", "peak", "song_seconds"):
                report[key] = val.strip()
        try:  # Report ist Arbeitsdatei — gehört nicht ins Zielverzeichnis
            rtxt.replace(work / (stem + "." + format + ".txt"))
        except OSError:
            pass
    result = report.get("result", "")
    exists = out.is_file()
    ok = proc.returncode == 0 and exists
    r: dict[str, Any] = {"ok": ok, "format": format,
                         "file": str(out) if exists else None,
                         "bytes": out.stat().st_size if exists else 0,
                         "seconds": _num(report.get("song_seconds")),
                         "peak": _num(report.get("peak"))}
    if start or end is not None:
        r["range"] = [start, end]
        if left is None:
            r["range_note"] = ("Playlist-Form unbekannt — Bereich wurde "
                               "nicht beschnitten, ganzer Song gerendert")
    if not ok:
        r["detail"] = (result.removeprefix("ERROR ").strip()
                       or f"LYNX.exe exit {proc.returncode}")
        if "silent" in result.lower():
            r["silent"] = True
            r["hint"] = ("Render unter -60 dBFS: Projekt spielt nichts "
                         "(Patterns/Clips leer oder stummgeschaltet) — Datei "
                         "existiert, ist aber stumm.")
        elif exists:
            r["hint"] = "Abbruch nach Renderstart — Datei unvollständig, " \
                        "Zustand prüfen statt wiederholen."
    elif not exists:
        r["detail"] = "LYNX meldet Erfolg, Ausgabedatei fehlt"
    return r
