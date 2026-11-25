"""Tests für den Test-Host (State-Datei,.pid-Erkennung) ohne echtes LYNX."""

import os

import pytest

from lynx_mcp import client, testhost


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """State/Log in tmp legen; Discovery ins Leere zeigen."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("LYNX_CONTROL_DISCOVERY", str(tmp_path / "no-conn.json"))
    return tmp_path


def test_state_file_roundtrip():
    assert testhost._read_state() is None
    testhost._write_state({"pid": 4242, "exe": r"C:\x\LYNX.exe"})
    state = testhost._read_state()
    assert state == {"pid": 4242, "exe": r"C:\x\LYNX.exe"}
    assert testhost._state_file().parent.exists()
    testhost._clear_state()
    assert testhost._read_state() is None


def test_is_our_instance_requires_matching_image(monkeypatch):
    assert not testhost._is_our_instance(None)
    state = {"pid": 1234, "exe": r"C:\x\LYNX.exe"}
    monkeypatch.setattr(testhost, "_process_image", lambda pid: None)
    assert not testhost._is_our_instance(state)          # PID tot
    monkeypatch.setattr(testhost, "_process_image", lambda pid: "notepad.exe")
    assert not testhost._is_our_instance(state)          # PID wiederverwendet!
    monkeypatch.setattr(testhost, "_process_image", lambda pid: "lynx.exe")
    assert testhost._is_our_instance(state)              # Gleiches Image (case-insensitiv)


def test_process_image_of_own_pid_is_python():
    # tasklist-Parsing gegen einen real laufenden Prozess (dieser Testprozess).
    image = testhost._process_image(os.getpid())
    if os.name == "nt":
        assert image and image.lower().startswith("python")
    else:  # pragma: no cover
        assert image is None


def test_process_image_survives_nonascii_tasklist_output(monkeypatch):
    """Regression: lokalisierte tasklist-Ausgabe enthält Nicht-ASCII-Bytes."""
    class FakeCompleted:
        stdout = ("INFO: Keine Tasks gefunden mit dem Namen »LYNX.exe«.".encode(
            "cp1252", errors="replace"))

    monkeypatch.setattr(client.subprocess, "run", lambda *a, **k: FakeCompleted())
    assert client.process_image(4242) is None

    class FakeTable:  # Kopfzeile mit undefinierbaren Bytes, dann Datenzeile
        stdout = b"\x81\x81\x81\x81\r\nLYNX.exe\t4242\tConsole\t1\t50.000 K\r\n"

    monkeypatch.setattr(client.subprocess, "run", lambda *a, **k: FakeTable())
    assert client.process_image(4242) == "LYNX.exe"


def test_status_without_anything(capsys):
    assert testhost.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "keine eigene Instanz aufgezeichnet" in out
    assert "nicht verfügbar" in out


def test_stop_without_state_is_noop(capsys):
    assert testhost.main(["stop"]) == 0
    assert "nichts zu tun" in capsys.readouterr().out


def test_stop_discards_stale_state_but_kills_nothing(monkeypatch):
    testhost._write_state({"pid": 999999, "exe": r"C:\x\LYNX.exe"})
    monkeypatch.setattr(testhost, "_process_image", lambda pid: None)
    assert testhost.main(["stop"]) == 0
    assert testhost._read_state() is None  # State aufgeräumt, kein Kill-Versuch
