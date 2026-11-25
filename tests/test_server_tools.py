"""M2-Tests: server.py Tool-Fläche gegen den Mock-Listener.

Prüft die Sicherheits-Semantik, nicht das Wire-Format (das testet test_client):
- Writes bekommen das Fence serverseitig eingesetzt; ohne frischen Read kein Request
- Read-Ops werden die expected*-Felder NICHT mitgeschickt (LYNX lehnt sie ab)
- project.edit verlangt einen echten Snapshot aus dem letzten Vollread
- Parameter-/Playlist-/Control-Guards stoppen ungültige Aufrufe vor dem Socket
"""

import json

import pytest

from lynx_mcp import client, fence, server

from .mock_lynx import MockLynx, make_read_pages

TRIPLE = {"projectId": "proj-1", "controlEpoch": "epoch-1", "revision": 7}


@pytest.fixture
def mock(tmp_path, monkeypatch):
    m = MockLynx()
    m.start()
    m.write_discovery(tmp_path / "connection.json")
    monkeypatch.setenv("LYNX_CONTROL_DISCOVERY", str(tmp_path / "connection.json"))
    monkeypatch.setattr(server, "_client", client.LynxClient(
        client.default_discovery_path()))
    monkeypatch.setattr(server, "_fence", fence.Fence())
    # Fast alle Ops antworten mit identität + leeren Zusatzfeldern
    m.respond("status", dict(TRIPLE))
    m.respond("api.describe", dict(TRIPLE, operations=["status"], capabilities={}))
    m.respond("session.inspect", dict(TRIPLE, channels=[], mixer=[], patterns=[]))
    for op in ("transport.play", "transport.stop", "history.undo", "history.redo",
               "tempo.set", "mixer.set", "channel.set", "channel.create",
               "instrument.replace", "effect.load", "effect.remove",
               "playlist.edit", "plugin.parameters_set", "pattern.create",
               "pattern.clone", "pattern.set", "pattern.replace_notes",
               "project.edit", "device.state", "changes"):
        m.respond(op, dict(TRIPLE))
    yield m
    m.stop()


def _last(mock, op):
    reqs = [r for r in mock.requests if r["op"] == op]
    return reqs[-1]["args"]


def test_status_observes_fence(mock):
    r = server.lynx_status()
    assert r["revision"] == 7
    assert server._fence.state.project_id == "proj-1"


def test_write_requires_fresh_state(mock):
    r = server.lynx_tempo_set(140.0)
    assert r["error"] == "stale_fence"
    assert mock.requests == []          # nichts ging raus
    server.lynx_status()                # Zustand holen
    assert server.lynx_tempo_set(140.0) == dict(TRIPLE)
    args = _last(mock, "tempo.set")
    assert args == {"bpm": 140.0, "expectedProjectId": "proj-1",
                    "expectedEpoch": "epoch-1", "expectedRevision": 7}


def test_read_ops_never_carry_fence_fields(mock):
    server.lynx_status()
    server.lynx_session()
    server.lynx_device_state()
    server.lynx_catalog("instruments", offset=2, limit=5)
    sess_args = _last(mock, "session.inspect")
    assert "expectedProjectId" not in sess_args
    cat = [r for r in mock.requests if r["op"] == "instrument.catalog"][-1]
    assert cat["args"] == {"offset": 2, "limit": 5}


def test_changed_error_stales_fence_and_blocks_writes(mock):
    server.lynx_status()
    mock.error("mixer.set", "Projekt geändert", "changed")
    r = server.lynx_mixer_set(0, volume=0.5)
    assert r["error"] == "changed"
    r = server.lynx_channel_set(1, muted=True)   # naechster Write ohne neuen Read
    assert r["error"] == "stale_fence"


def test_control_tools_need_at_least_one_value(mock):
    server.lynx_status()
    assert server.lynx_mixer_set(0)["error"] == "invalid"
    assert server.lynx_channel_set(2)["error"] == "invalid"
    assert mock.requests[-1]["op"] == "status"   # keine Requests durch Guards


def test_plugin_parameters_validates_before_wire(mock):
    server.lynx_status()
    assert server.lynx_plugin_parameters({}, [{"index": 0, "value": 0.5}])["error"] == "invalid"
    assert server.lynx_plugin_parameters({"kind": "instrument"}, [])["error"] == "invalid"
    server.lynx_plugin_parameters(
        {"kind": "effect", "mixerIndex": 0, "effectIndex": 0},
        [{"index": 1, "value": 0.25, "expectedValue": 0.3}])
    args = _last(mock, "plugin.parameters_set")
    assert args["target"] == {"kind": "effect", "mixerIndex": 0, "effectIndex": 0}
    assert args["parameters"][0]["expectedValue"] == 0.3


def test_playlist_edit_count_guard(mock):
    server.lynx_status()
    assert server.lynx_playlist_edit([])["error"] == "invalid"
    assert server.lynx_playlist_edit([{"action": "remove", "clipId": "c"}]) == dict(TRIPLE)


def test_patch_needs_snapshot_from_full_read(mock):
    server.lynx_status()                      # Fence frisch, aber kein Snapshot
    r = server.lynx_patch([{"op": "replace", "path": "/bpm", "value": 140}])
    assert r["error"] == "no_snapshot"
    doc = json.dumps({"bpm": 130.0}).encode()
    mock.respond("project.read", make_read_pages(doc, page_size=64))
    r = server.lynx_read(scope="summary")
    assert r["tempo"]["bpm"] == 130.0
    assert server.lynx_patch([{"op": "test", "path": "/bpm", "value": 130.0}]) == dict(TRIPLE)
    args = _last(mock, "project.edit")
    assert args["snapshotId"] == "snap-mock-1"
    # Snapshot ist verbraucht: zweiter Patch ohne neuen Read -> no_snapshot
    assert server.lynx_patch([{"op": "test", "path": "/x", "value": 1}])["error"] == "no_snapshot"


def test_transport_stop_works_without_fresh_fence(mock):
    r = server.lynx_transport("stop")          # nie ein Read zuvor
    assert "error" not in r
    assert _last(mock, "transport.stop") == {}
    assert r["revision"] == 7


def test_changes_gap_marks_stale(mock):
    server.lynx_status()
    mock.respond("changes", dict(TRIPLE, gap=True, changes=[], hasMore=False))
    r = server.lynx_changes(from_revision=1)
    assert r["gap"] is True and "hint" in r
    assert server.lynx_pattern_set(0, name="X")["error"] == "stale_fence"


def test_notes_replace_guards(mock):
    server.lynx_status()
    assert server.lynx_notes_replace(pattern_index=0)["error"] == "invalid"
    assert server.lynx_notes_replace(pattern_index=0,
                                     notes=[{"k": 1}] * 2001)["error"] == "limit"
    server.lynx_notes_replace(pattern_index=1, notes=[{"start": 0}])
    args = _last(mock, "pattern.replace_notes")
    assert args["index"] == 1 and len(args["notes"]) == 1


def test_summary_sets_fence_and_snapshot_together(mock):
    doc = json.dumps({"bpm": 120.0,
                      "patterns": [{"name": "A"}, {"name": "B"}]}).encode()
    mock.respond("project.read", make_read_pages(doc, page_size=64))
    r = server.lynx_read(scope="summary")
    assert r["collections"]["patterns"]["count"] == 2
    assert r["fence"]["revision"] == 7
    assert server._fence.state.snapshot_id == "snap-mock-1"
    # Write nach summary: Fence-Felder kommen automatisch mit
    server.lynx_pattern_create(name="C")
    args = _last(mock, "pattern.create")
    assert args["expectedRevision"] == 7 and args["name"] == "C"


def test_large_reply_is_capped_not_dumped(mock):
    server.lynx_status()
    mock.respond("session.inspect", dict(TRIPLE, blob="x" * (server.MAX_REPLY_CHARS + 10)))
    r = server.lynx_session()
    assert r.get("truncated") is True and "lynx_snapshot" in r["hint"]


def test_out_dir_prefers_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LYNX_MCP_OUT_DIR", str(tmp_path / "woanders"))
    assert server.out_dir() == tmp_path / "woanders"


def test_out_dir_falls_back_to_localappdata_outside_checkout(tmp_path, monkeypatch):
    # simuliere einen uvx-Lauf: Lynx_mcp in site-packages ohne pyproject.toml
    monkeypatch.delenv("LYNX_MCP_OUT_DIR", raising=False)
    monkeypatch.setattr(server, "__file__",
                        str(tmp_path / "site-packages" / "lynx_mcp" / "server.py"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lap"))
    assert server.out_dir() == tmp_path / "lap" / "lynx-mcp" / "out"
