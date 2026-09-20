#!/usr/bin/env python3
import time
from typing import Any

import requests

import slowban


_original_get = requests.Session.get
_TORRENTS_INFO_PATH = "/api/v2/torrents/info"
_TORRENTS_INFO_FILTER = "downloading"


def resilient_get(self: requests.Session, url: str, **kwargs: Any) -> requests.Response:
    """Retry transient qBittorrent GET failures once with a fresh connection.

    The /torrents/info poll is limited to downloading-state torrents and is
    intentionally forced onto a fresh TCP connection every time. This avoids
    transferring the full qBittorrent library on every Slowban poll and also
    avoids reused keep-alive connections that qBittorrent may reset.
    """
    path = url[len(slowban.QBT_URL):] if url.startswith(slowban.QBT_URL) else url

    if path == _TORRENTS_INFO_PATH:
        # Slowban only scans incomplete download torrents for peers. Let
        # qBittorrent filter the library server-side instead of returning every
        # seeding/completed torrent and discarding it locally afterwards.
        params = dict(kwargs.pop("params", {}) or {})
        params.setdefault("filter", _TORRENTS_INFO_FILTER)
        kwargs["params"] = params

        # Preserve cookies/authentication, but drop pooled TCP connections before
        # the poll and ask qBittorrent to close the connection afterwards.
        self.close()
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Connection"] = "close"
        kwargs["headers"] = headers

    try:
        return _original_get(self, url, **kwargs)
    except (requests.ConnectionError, requests.Timeout) as exc:
        slowban.log(
            f"Temporary qBittorrent API connection error on GET {path}: {exc}. "
            "Retrying once with a fresh connection.",
            "WARN",
        )
        self.close()
        time.sleep(0.75)
        return _original_get(self, url, **kwargs)


requests.Session.get = resilient_get


if __name__ == "__main__":
    slowban.log(
        "Optimized torrent polling enabled: qBittorrent filters /torrents/info "
        "to downloading-state torrents before sending the response.",
        "INFO",
    )
    slowban.main()
