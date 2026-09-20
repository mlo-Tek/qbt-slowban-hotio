#!/usr/bin/env python3
import time
from typing import Any

import requests

import slowban


_original_get = requests.Session.get
_TORRENTS_INFO_PATH = "/api/v2/torrents/info"


def resilient_get(self: requests.Session, url: str, **kwargs: Any) -> requests.Response:
    """Retry transient qBittorrent GET failures once with a fresh connection.

    The large /torrents/info poll is intentionally forced onto a fresh TCP
    connection every time. qBittorrent has been observed resetting reused
    keep-alive connections for this endpoint on large libraries.
    """
    path = url[len(slowban.QBT_URL):] if url.startswith(slowban.QBT_URL) else url

    if path == _TORRENTS_INFO_PATH:
        # Preserve cookies/authentication, but drop pooled TCP connections before
        # the large poll and ask qBittorrent to close the connection afterwards.
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
    slowban.main()
