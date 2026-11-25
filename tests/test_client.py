"""M1-Tests: client.py gegen den Mock-Listener (Handshake, Ops, Paging, Fence).

Negativtests aus PLAN.md §5/M1: verwaiste/manipulierte Discovery-Dateien und
ein Server mit falschem Proof werden abgelehnt, ohne dass unser Q rausgeht.
"""

import hashlib
import json
import secrets

import pytest

from lynx_mcp import client

from .mock_lynx import MockLynx, make_read_pages


@pytest.fixture
def mock(tmp_path, monkeypatch):
    m = MockLynx()
    m.start()
    m.write_discovery(tmp_path / "connection.json")
    monkeypatch.setenv("LYNX_CONTROL_DISCOVERY", str(tmp_path / "connection.json"))
    yield m
    m.stop()


def _client(m):
    return client.LynxClient(client.default_discovery_path())


def test_handshake_and_status_roundtrip(mock):
    mock.respond("status", {"projectId": "p1", "controlEpoch": "e1",
                           "revision": 42, "bpm": 130.0})
    result = _client(mock).request("status")
    assert result["revision"] == 42
    assert mock.requests[0]["op"] == "status"
    assert mock.client_proofs_ok == [True]


def test_server_proof_verified_before_auth_sent(tmp_path, monkeypatch):
    # Discovery-Token gegen Token des Servers austauschen -> Proof P schlägt fehl,
    # unser Q darf den Socket nie erreichen.
    m = MockLynx(token=secrets.token_hex(32))
    m.start()
    p = tmp_path / "connection.json"
    m.write_discovery(p)
    info = json.loads(p.read_text())
    info["token"] = "0" * 64  # manipuliert/falsch
    p.write_text(json.dumps(info))
    monkeypatch.setenv("LYNX_CONTROL_DISCOVERY", str(p))
    with pytest.raises(client.ProtocolError, match="Server-Proof"):
        _client(m).request("status")
    assert m.client_proofs_ok == []  # Q wurde nie geprüft/gesendet
    m.stop()


def test_stale_discovery_pid_rejected(tmp_path, monkeypatch):
    m = MockLynx()
    m.start()
    p = tmp_path / "connection.json"
    m.write_discovery(p, pid=0x7FF00000)  # sehr unwahrscheinlich lebend
    monkeypatch.setenv("LYNX_CONTROL_DISCOVERY", str(p))
    with pytest.raises(client.DiscoveryError, match="verwaist"):
        _client(m).request("status")
    assert m.client_proofs_ok == []  # Handshake gar nicht erst versucht
    m.stop()


def test_error_codes_map_to_lynxerror(mock):
    mock.error("pattern.set", "revision weicht ab", "changed")
    with pytest.raises(client.LynxError) as excinfo:
        _client(mock).request("pattern.set", {"index": 0, "name": "X"})
    assert excinfo.value.code == "changed"
    assert not excinfo.value.uncertain


def test_uncertain_error_flagged(mock):
    mock.error("project.edit", "antwortzeit", "uncertain", uncertain=True)
    with pytest.raises(client.LynxError) as excinfo:
        _client(mock).request("project.edit", {"patch": []})
    assert excinfo.value.uncertain


def test_project_read_full_paging_with_utf8_split(mock):
    doc = json.dumps({"bpm": 130.0, "patterns": [{"name": "Stühl"},
                                                 {"name": "Brücke"}]},
                     ensure_ascii=False).encode("utf-8")
    mock.respond("project.read", make_read_pages(doc, page_size=7))  # mitten in Umlauten
    project, meta = _client(mock).project_read_full(max_pages=50, page_limit=7)
    assert project["patterns"][0]["name"] == "Stühl"
    assert meta["documentHash"] == hashlib.sha256(doc).hexdigest()
    assert meta["revision"] == 7


def test_paging_cap_enforced(mock):
    doc = b'{"a":' + b" " * 300 + b'1}'
    mock.respond("project.read", make_read_pages(doc, page_size=8))
    with pytest.raises(client.LynxError) as excinfo:
        _client(mock).project_read_full(max_pages=4, page_limit=8)
    assert excinfo.value.code == "limit"


def test_frame_size_limit_blocks_oversized_request(mock):
    with pytest.raises(client.ProtocolError, match="Größenlimit"):
        _client(mock).request("project.read", {"blob": "x" * (1024 * 1024)})


def test_close_after_result_one_op_per_connection(mock):
    mock.respond("status", {"projectId": "p", "controlEpoch": "e", "revision": 1})
    c = _client(mock)
    c.request("status")
    c.request("status")
    assert len(mock.requests) == 2
    assert len(mock.client_proofs_ok) == 2  # zwei Handshakes = zwei Verbindungen
