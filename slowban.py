#!/usr/bin/env python3
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set

import requests


QBT_URL = os.environ.get("QBT_URL", "http://10.20.20.15:8080").rstrip("/")
QBT_USERNAME = os.environ.get("QBT_USERNAME", "")
QBT_PASSWORD = os.environ.get("QBT_PASSWORD", "")

SLOWBAN_THRESHOLD_TIME = int(os.environ.get("SLOWBAN_THRESHOLD_TIME", "180"))
SLOWBAN_WARN_TIME = int(os.environ.get("SLOWBAN_WARN_TIME", "90"))
SLOWBAN_MIN_SPEED = int(os.environ.get("SLOWBAN_MIN_SPEED", "50768"))
SLOWBAN_POLL_INTERVAL = int(os.environ.get("SLOWBAN_POLL_INTERVAL", "10"))
SLOWBAN_SUMMARY_INTERVAL = int(os.environ.get("SLOWBAN_SUMMARY_INTERVAL", "600"))

SLOWBAN_LOG_LEVEL = os.environ.get("SLOWBAN_LOG_LEVEL", "INFO").upper()
SLOWBAN_DRY_RUN = os.environ.get("SLOWBAN_DRY_RUN", "false").lower() == "true"
SLOWBAN_STATE_FILE = os.environ.get("SLOWBAN_STATE_FILE", "/state/slowban_state.json")

SLOWBAN_CLEAR_PERIODICALLY = os.environ.get("SLOWBAN_CLEAR_PERIODICALLY", "").strip()
SLOWBAN_BANNED_PEERS = os.environ.get("SLOWBAN_BANNED_PEERS", "").strip()

SLOWBAN_LOG_DIR = os.environ.get("SLOWBAN_LOG_DIR", "/logs")
SLOWBAN_LOG_RETENTION_DAYS = int(os.environ.get("SLOWBAN_LOG_RETENTION_DAYS", "7"))
SLOWBAN_LOG_UNBAN_DETAILS = os.environ.get("SLOWBAN_LOG_UNBAN_DETAILS", "false").lower() == "true"
SLOWBAN_COLOR_LOGS = os.environ.get("SLOWBAN_COLOR_LOGS", "true").lower() == "true"

LOG_LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 30,
    "BAN": 35,
    "UNBAN": 36,
    "ERROR": 40,
}

ANSI_RESET = "\033[0m"
ANSI_COLORS = {
    "DEBUG": "\033[90m",
    "INFO": "\033[92m",
    "WARN": "\033[93m",
    "BAN": "\033[91m",
    "UNBAN": "\033[96m",
    "ERROR": "\033[95m",
}

STATE_META_KEYS = {
    "last_clear_run",
    "last_clear_existing_count",
    "last_clear_unbanned_count",
    "last_clear_permanent_count",
    "bans_total",
    "bans_since_last_summary",
    "unbans_total",
    "unbans_since_last_summary",
    "last_summary_ts",
}

session = requests.Session()
session.headers.update({"Referer": QBT_URL})

CURRENT_LOG_PATH: Path | None = None
CURRENT_LOG_SLOT: str | None = None


def level_value(level: str) -> int:
    return LOG_LEVELS.get(level.upper(), 20)


def should_emit(level: str) -> bool:
    return level_value(level) >= level_value(SLOWBAN_LOG_LEVEL)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def log_line(message: str, level: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"[{level}] {ts} {message}"


def console_print(line: str, level: str) -> None:
    if SLOWBAN_COLOR_LOGS:
        color = ANSI_COLORS.get(level.upper(), "")
        if color:
            print(f"{color}{line}{ANSI_RESET}", flush=True)
            return
    print(line, flush=True)


def current_log_slot(now: datetime) -> str:
    hour_slot = (now.hour // 2) * 2
    return now.strftime(f"%Y-%m-%d_{hour_slot:02d}00")


def current_log_file(now: datetime) -> Path:
    return Path(SLOWBAN_LOG_DIR) / f"slowban-{current_log_slot(now)}.log"


def prune_old_logs() -> None:
    ensure_dir(SLOWBAN_LOG_DIR)
    cutoff = time.time() - (SLOWBAN_LOG_RETENTION_DAYS * 86400)

    for entry in Path(SLOWBAN_LOG_DIR).glob("slowban-*.log"):
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
        except FileNotFoundError:
            pass
        except Exception as e:
            line = log_line(f"Failed to prune old log '{entry}': {e}", "ERROR")
            console_print(line, "ERROR")


def rotate_log_if_needed() -> None:
    global CURRENT_LOG_PATH, CURRENT_LOG_SLOT

    ensure_dir(SLOWBAN_LOG_DIR)
    now = datetime.now()
    slot = current_log_slot(now)
    path = current_log_file(now)

    if CURRENT_LOG_SLOT != slot or CURRENT_LOG_PATH != path:
        CURRENT_LOG_SLOT = slot
        CURRENT_LOG_PATH = path
        prune_old_logs()


def write_file_log(line: str) -> None:
    rotate_log_if_needed()
    if CURRENT_LOG_PATH is None:
        return
    with open(CURRENT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def log(message: str, level: str = "INFO") -> None:
    level = level.upper()
    if not should_emit(level):
        return

    line = log_line(message, level)
    console_print(line, level)

    try:
        write_file_log(line)
    except Exception as e:
        fallback = log_line(f"Failed to write file log: {e}", "ERROR")
        console_print(fallback, "ERROR")


def ensure_state_dir() -> None:
    state_dir = os.path.dirname(SLOWBAN_STATE_FILE)
    if state_dir:
        os.makedirs(state_dir, exist_ok=True)


def default_state() -> Dict[str, Any]:
    return {
        "bans_total": 0,
        "bans_since_last_summary": 0,
        "unbans_total": 0,
        "unbans_since_last_summary": 0,
        "last_summary_ts": 0.0,
    }


def load_state() -> Dict[str, Any]:
    ensure_state_dir()
    state = default_state()
    if not os.path.exists(SLOWBAN_STATE_FILE):
        return state
    try:
        with open(SLOWBAN_STATE_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        state.update(loaded)
        return state
    except Exception as e:
        log(f"Could not load state file, starting fresh: {e}", "WARN")
        return state


def save_state(state: Dict[str, Any]) -> None:
    ensure_state_dir()
    tmp_file = f"{SLOWBAN_STATE_FILE}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp_file, SLOWBAN_STATE_FILE)


def login() -> None:
    response = session.post(
        f"{QBT_URL}/api/v2/auth/login",
        data={"username": QBT_USERNAME, "password": QBT_PASSWORD},
        timeout=15,
    )

    if not (200 <= response.status_code < 300):
        raise RuntimeError(
            f"Login failed: HTTP {response.status_code}: {response.text}"
        )

    if not session.cookies:
        raise RuntimeError(
            "Login failed: qBittorrent returned no session cookie"
        )

    log(
        f"Logged into qBittorrent at {QBT_URL} "
        f"(HTTP {response.status_code}, session cookie received)",
        "INFO",
    )


def get_torrents() -> List[Dict[str, Any]]:
    response = session.get(f"{QBT_URL}/api/v2/torrents/info", timeout=30)
    response.raise_for_status()
    return response.json()


def get_peers(torrent_hash: str) -> Dict[str, Any]:
    response = session.get(
        f"{QBT_URL}/api/v2/sync/torrentPeers",
        params={"hash": torrent_hash, "rid": 0},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return data.get("peers", {})


def increment_ban_counters(state: Dict[str, Any]) -> None:
    state["bans_total"] = int(state.get("bans_total", 0)) + 1
    state["bans_since_last_summary"] = int(state.get("bans_since_last_summary", 0)) + 1


def increment_unban_counters(state: Dict[str, Any], count: int) -> None:
    if count <= 0:
        return
    state["unbans_total"] = int(state.get("unbans_total", 0)) + count
    state["unbans_since_last_summary"] = int(state.get("unbans_since_last_summary", 0)) + count


def ban_peer(peer_address: str, torrent_name: str, state: Dict[str, Any]) -> None:
    if SLOWBAN_DRY_RUN:
        log(f"[DRY RUN] Would ban peer {peer_address} on torrent '{torrent_name}'", "BAN")
        increment_ban_counters(state)
        return

    response = session.post(
        f"{QBT_URL}/api/v2/transfer/banPeers",
        data={"peers": peer_address},
        timeout=15,
    )
    response.raise_for_status()
    increment_ban_counters(state)
    log(f"Banned peer {peer_address} on torrent '{torrent_name}'", "BAN")


def get_preferences() -> Dict[str, Any]:
    response = session.get(f"{QBT_URL}/api/v2/app/preferences", timeout=30)
    response.raise_for_status()
    return response.json()


def set_preferences(payload: Dict[str, Any]) -> None:
    response = session.post(
        f"{QBT_URL}/api/v2/app/setPreferences",
        data={"json": json.dumps(payload)},
        timeout=30,
    )
    response.raise_for_status()


def normalize_peer_list(raw_value: str) -> List[str]:
    if not raw_value:
        return []
    normalized = raw_value.replace("\r", "").replace("\n", ",")
    return [x.strip() for x in normalized.split(",") if x.strip()]


def dedupe_preserve_order(items: List[str]) -> List[str]:
    result: List[str] = []
    seen: Set[str] = set()
    for item in items:
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def get_manual_ban_list() -> List[str]:
    prefs = get_preferences()
    raw = prefs.get("banned_IPs", "") or prefs.get("bannedIPs", "") or ""
    return dedupe_preserve_order(normalize_peer_list(raw))


def set_manual_ban_list(peers: List[str]) -> None:
    peers = dedupe_preserve_order([p.strip() for p in peers if p.strip()])

    if SLOWBAN_DRY_RUN:
        if peers:
            log(f"[DRY RUN] Would set manual ban list to: {','.join(peers)}", "UNBAN")
        else:
            log("[DRY RUN] Would clear manual ban list", "UNBAN")
        return

    payload_value = "\n".join(peers) if peers else ""
    set_preferences({"banned_IPs": payload_value})

    if peers:
        log(f"Updated manual ban list with {len(peers)} entries", "UNBAN")
    else:
        log("Cleared manual ban list", "UNBAN")


def get_permanent_bans() -> List[str]:
    return dedupe_preserve_order(normalize_peer_list(SLOWBAN_BANNED_PEERS))


def should_track_peer(peer: Dict[str, Any]) -> bool:
    up_speed = int(peer.get("up_speed", 0) or 0)
    return up_speed > 0 and up_speed < SLOWBAN_MIN_SPEED


def parse_field(field: str, min_v: int, max_v: int) -> Set[int]:
    if field == "*":
        return set(range(min_v, max_v + 1))

    values: Set[int] = set()
    for token in field.split(","):
        token = token.strip()
        if not token:
            continue
        if token.startswith("*/"):
            step = int(token[2:])
            values.update(range(min_v, max_v + 1, step))
        elif "-" in token:
            start, end = token.split("-", 1)
            values.update(range(int(start), int(end) + 1))
        else:
            values.add(int(token))

    return {v for v in values if min_v <= v <= max_v}


def cron_matches(dt: datetime, expr: str) -> bool:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("Cron expression must have 5 fields")

    minute_s, hour_s, dom_s, month_s, dow_s = parts
    minutes = parse_field(minute_s, 0, 59)
    hours = parse_field(hour_s, 0, 23)
    dom = parse_field(dom_s, 1, 31)
    months = parse_field(month_s, 1, 12)
    dow = parse_field(dow_s, 0, 6)

    cron_dow = (dt.weekday() + 1) % 7

    return (
        dt.minute in minutes
        and dt.hour in hours
        and dt.day in dom
        and dt.month in months
        and cron_dow in dow
    )


def should_run_clear(now: datetime, state: Dict[str, Any]) -> bool:
    if not SLOWBAN_CLEAR_PERIODICALLY:
        return False

    current_minute_key = now.strftime("%Y-%m-%d %H:%M")
    if state.get("last_clear_run") == current_minute_key:
        return False

    try:
        return cron_matches(now, SLOWBAN_CLEAR_PERIODICALLY)
    except Exception as e:
        log(f"Invalid SLOWBAN_CLEAR_PERIODICALLY value '{SLOWBAN_CLEAR_PERIODICALLY}': {e}", "ERROR")
        return False


def clear_bans_preserve_permanent(state: Dict[str, Any]) -> None:
    existing = get_manual_ban_list()
    permanent = get_permanent_bans()
    permanent_set = set(permanent)
    unbanned = [peer for peer in existing if peer not in permanent_set]

    log(
        f"Clearing ban list. Existing entries={len(existing)}, unbanned={len(unbanned)}, permanent entries={len(permanent)}",
        "UNBAN",
    )

    if SLOWBAN_LOG_UNBAN_DETAILS and unbanned:
        for peer in unbanned:
            log(f"Unbanned peer {peer}", "UNBAN")

    set_manual_ban_list(permanent)
    increment_unban_counters(state, len(unbanned))

    state["last_clear_run"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    state["last_clear_existing_count"] = len(existing)
    state["last_clear_unbanned_count"] = len(unbanned)
    state["last_clear_permanent_count"] = len(permanent)

    if permanent:
        log(f"Re-applied {len(permanent)} permanent bans", "UNBAN")
    else:
        log("Ban list cleared with no permanent bans configured", "UNBAN")


def tracked_peer_keys(state: Dict[str, Any]) -> List[str]:
    return [k for k in state.keys() if k not in STATE_META_KEYS]


def maybe_emit_summary(
    state: Dict[str, Any],
    torrent_count: int,
    active_peer_count: int,
) -> None:
    now_ts = time.time()
    last_summary_ts = float(state.get("last_summary_ts", 0.0))
    if now_ts - last_summary_ts < SLOWBAN_SUMMARY_INTERVAL:
        return

    tracked_keys = tracked_peer_keys(state)
    warned_count = sum(1 for k in tracked_keys if bool(state.get(k, {}).get("warned", False)))
    tracked_count = len(tracked_keys)

    bans_total = int(state.get("bans_total", 0))
    bans_since_last_summary = int(state.get("bans_since_last_summary", 0))
    unbans_total = int(state.get("unbans_total", 0))
    unbans_since_last_summary = int(state.get("unbans_since_last_summary", 0))

    log(
        "Summary: "
        f"alive=yes, torrents={torrent_count}, active_peers={active_peer_count}, "
        f"tracked_slow_peers={tracked_count}, warned_peers={warned_count}, "
        f"dry_run={SLOWBAN_DRY_RUN}, bans_total={bans_total}, "
        f"bans_since_last_summary={bans_since_last_summary}, "
        f"unbans_total={unbans_total}, unbans_since_last_summary={unbans_since_last_summary}",
        "INFO",
    )

    state["last_summary_ts"] = now_ts
    state["bans_since_last_summary"] = 0
    state["unbans_since_last_summary"] = 0


def main() -> None:
    ensure_dir(SLOWBAN_LOG_DIR)
    rotate_log_if_needed()

    if SLOWBAN_WARN_TIME >= SLOWBAN_THRESHOLD_TIME:
        raise RuntimeError("SLOWBAN_WARN_TIME must be lower than SLOWBAN_THRESHOLD_TIME")

    log("Starting qbt-slowban-hotio helper", "INFO")
    log(
        f"Settings: threshold={SLOWBAN_THRESHOLD_TIME}s, warn_time={SLOWBAN_WARN_TIME}s, "
        f"min_speed={SLOWBAN_MIN_SPEED}B/s, poll_interval={SLOWBAN_POLL_INTERVAL}s, "
        f"summary_interval={SLOWBAN_SUMMARY_INTERVAL}s, dry_run={SLOWBAN_DRY_RUN}",
        "INFO",
    )
    log(
        f"Time-sliced file logging enabled: dir={SLOWBAN_LOG_DIR}, rotation=2h, retention_days={SLOWBAN_LOG_RETENTION_DAYS}",
        "INFO",
    )
    if SLOWBAN_CLEAR_PERIODICALLY:
        log(f"Periodic unban schedule enabled: {SLOWBAN_CLEAR_PERIODICALLY}", "INFO")
    if SLOWBAN_BANNED_PEERS:
        log(f"Permanent banned peers configured: {SLOWBAN_BANNED_PEERS}", "INFO")

    state = load_state()
    login()

    while True:
        loop_start = time.time()

        try:
            rotate_log_if_needed()

            now_dt = datetime.now()
            if should_run_clear(now_dt, state):
                clear_bans_preserve_permanent(state)
                save_state(state)

            torrents = get_torrents()
            active_peer_count = 0
            seen_state_keys: Set[str] = set()

            for torrent in torrents:
                torrent_hash = torrent.get("hash")
                torrent_name = torrent.get("name", torrent_hash or "unknown")
                if not torrent_hash:
                    continue

                peers = get_peers(torrent_hash)
                active_peer_count += len(peers)

                for peer_address, peer_data in peers.items():
                    state_key = f"{torrent_hash}|{peer_address}"
                    seen_state_keys.add(state_key)

                    if should_track_peer(peer_data):
                        now_ts = time.time()
                        up_speed = int(peer_data.get("up_speed", 0) or 0)
                        client = peer_data.get("client", "")
                        country = peer_data.get("country", "")
                        connection = peer_data.get("connection", "")

                        existing = state.get(state_key, {})
                        first_seen = float(existing.get("first_seen", now_ts))
                        warned = bool(existing.get("warned", False))
                        slow_for = int(now_ts - first_seen)
                        warn_remaining = max(0, SLOWBAN_THRESHOLD_TIME - slow_for)

                        state[state_key] = {
                            "first_seen": first_seen,
                            "last_seen": now_ts,
                            "torrent_hash": torrent_hash,
                            "torrent_name": torrent_name,
                            "peer_address": peer_address,
                            "up_speed": up_speed,
                            "client": client,
                            "country": country,
                            "connection": connection,
                            "warned": warned,
                        }

                        if slow_for >= SLOWBAN_WARN_TIME and not warned:
                            log(
                                f"Peer '{peer_address}' on torrent '{torrent_name}' has stayed below "
                                f"{SLOWBAN_MIN_SPEED}B/s for {slow_for}s "
                                f"(current {up_speed}B/s, client='{client}', country='{country}', "
                                f"connection='{connection}'). Ban in {warn_remaining}s if still below threshold.",
                                "WARN",
                            )
                            state[state_key]["warned"] = True

                        if slow_for >= SLOWBAN_THRESHOLD_TIME:
                            log(
                                f"Threshold reached for peer '{peer_address}' on torrent '{torrent_name}' "
                                f"after {slow_for}s below {SLOWBAN_MIN_SPEED}B/s (current {up_speed}B/s).",
                                "WARN",
                            )
                            ban_peer(peer_address, torrent_name, state)
                            state.pop(state_key, None)
                    else:
                        if state_key in state:
                            previous = state[state_key]
                            slow_for = int(time.time() - float(previous.get("first_seen", time.time())))
                            if previous.get("warned", False):
                                log(
                                    f"Peer '{peer_address}' on torrent '{torrent_name}' recovered before ban "
                                    f"after {slow_for}s below threshold.",
                                    "INFO",
                                )
                            state.pop(state_key, None)

            stale_keys = [
                key for key in list(state.keys())
                if key not in STATE_META_KEYS and key not in seen_state_keys
            ]
            for key in stale_keys:
                state.pop(key, None)

            maybe_emit_summary(state, len(torrents), active_peer_count)
            save_state(state)

        except requests.HTTPError as e:
            log(f"HTTP error: {e}", "ERROR")
            try:
                login()
            except Exception as relogin_error:
                log(f"Re-login failed: {relogin_error}", "ERROR")
        except requests.RequestException as e:
            log(f"Request error: {e}", "ERROR")
        except Exception as e:
            log(f"Unexpected error: {e}", "ERROR")

        elapsed = time.time() - loop_start
        sleep_for = max(1, SLOWBAN_POLL_INTERVAL - int(elapsed))
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
