#!/usr/bin/env python3
"""Self-check for the scope switches and the API key header.

Run it with `python3 test_slowban.py`. It needs `requests` installed, because
slowban.py imports it, but it never opens a connection: every assertion below
is about a pure decision function or about the session headers the module sets
up at import time.

The switches are read once at import, so each case reloads the module under the
environment it wants to test.
"""
import importlib
import os
import sys


def load(**env):
    for key in list(os.environ):
        if key.startswith("SLOWBAN_") or key.startswith("QBT_"):
            del os.environ[key]
    os.environ.update(env)
    sys.modules.pop("slowban", None)
    return importlib.import_module("slowban")


def test_defaults_are_unchanged():
    m = load(SLOWBAN_MIN_SPEED="1000")
    assert m.should_track_peer({"up_speed": 500}) is True
    # A peer at exactly 0 B/s stays untracked unless the switch is set.
    assert m.should_track_peer({"up_speed": 0}) is False
    # A complete peer and a downloading torrent are both in scope by default.
    assert m.should_track_peer({"up_speed": 500, "progress": 1.0}) is True
    assert m.should_scan_torrent({"amount_left": 12345}) is True


def test_idle_peers_switch():
    m = load(SLOWBAN_MIN_SPEED="1000", SLOWBAN_INCLUDE_IDLE_PEERS="true")
    assert m.should_track_peer({"up_speed": 0}) is True
    # A fast peer is still out of scope, whatever the switch says.
    assert m.should_track_peer({"up_speed": 5000}) is False


def test_complete_peers_switch():
    m = load(SLOWBAN_MIN_SPEED="1000", SLOWBAN_SKIP_COMPLETE_PEERS="true")
    assert m.should_track_peer({"up_speed": 500, "progress": 1.0}) is False
    assert m.should_track_peer({"up_speed": 500, "progress": 0.4}) is True


def test_finished_torrents_switch():
    m = load(SLOWBAN_ONLY_FINISHED_TORRENTS="true")
    assert m.should_scan_torrent({"amount_left": 0}) is True
    assert m.should_scan_torrent({"amount_left": 12345}) is False


def test_api_key_sets_bearer_header():
    m = load(QBT_API_KEY="secret")
    assert m.session.headers["Authorization"] == "Bearer secret"

    m = load(QBT_USERNAME="admin", QBT_PASSWORD="pw")
    assert "Authorization" not in m.session.headers


def main():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"{len(tests)} passed")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
