"""Smoke-Tests für das Repo-Skelett (M0).

Mock-Listener für Handshake/Ops folgen in M1 (§6: tests/).
"""

from pathlib import Path

import lynx_mcp
from lynx_mcp import client, fence


def test_version_present():
    assert isinstance(lynx_mcp.__version__, str) and lynx_mcp.__version__


def test_default_discovery_path(monkeypatch, tmp_path):
    monkeypatch.setenv("LYNX_CONTROL_DISCOVERY", str(tmp_path / "conn.json"))
    assert client.default_discovery_path() == tmp_path / "conn.json"


def test_load_discovery_rejects_missing(tmp_path):
    try:
        client.load_discovery(tmp_path / "nope.json")
    except client.DiscoveryError:
        return
    raise AssertionError("DiscoveryError erwartet")


def test_load_discovery_rejects_foreign_protocol(tmp_path):
    p = tmp_path / "conn.json"
    p.write_text('{"protocol": "lynx-control/0", "port": 1, "pid": 2, "token": "x"}')
    try:
        client.load_discovery(p)
    except client.DiscoveryError as exc:
        assert "lynx-control/1" in str(exc)
        return
    raise AssertionError("DiscoveryError erwartet")


def test_fence_requires_fresh_read():
    f = fence.Fence()
    try:
        f.require_fresh("project.edit")
    except fence.StaleFenceError:
        pass
    else:
        raise AssertionError("StaleFenceError erwartet")
    f.observe(project_id="p1", control_epoch=3, revision=10)
    f.require_fresh("project.edit")  # darf jetzt nicht mehr werfen
    f.mark_stale("changed")
    assert f.stale_reason == "changed"
