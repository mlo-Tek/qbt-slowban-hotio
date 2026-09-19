#!/usr/bin/env python3
import time
from typing import Any

import requests

import slowban


_original_get = requests.Session.get


def resilient_get(self: requests.Session, url: str, **kwargs: Any) -> requests.Response:
    """Retry transient qBittorrent GET failures once with a fresh connection."""
    try:
        return _original_get(self, url, **kwargs)
    except (requests.ConnectionError, requests.Timeout) as exc:
        path = url[len(slowban.QBT_URL):] if url.startswith(slowban.QBT_URL) else url
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
