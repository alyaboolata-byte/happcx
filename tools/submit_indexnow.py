#!/usr/bin/env python3
"""Notify IndexNow about changed happ.cx pages after they are published."""

import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

HOST = "happ.cx"
KEY_LOCATION = f"https://{HOST}/indexnow-key.txt"
ENDPOINT = "https://api.indexnow.org/indexnow"


def main():
    urls = list(dict.fromkeys(sys.argv[1:]))
    if not urls or any(urlparse(url).scheme != "https" or urlparse(url).netloc != HOST for url in urls):
        raise SystemExit("Usage: python3 submit_indexnow.py https://happ.cx/ [https://happ.cx/page ...]")
    key = (Path(__file__).resolve().parent.parent / "indexnow-key.txt").read_text(encoding="utf-8").strip()
    with urlopen(KEY_LOCATION, timeout=15) as response:
        if response.status != 200 or response.read().decode("utf-8").strip() != key:
            raise SystemExit("Published IndexNow key file does not match the local key.")
    payload = json.dumps({"host": HOST, "key": key, "keyLocation": KEY_LOCATION, "urlList": urls}).encode("utf-8")
    request = Request(ENDPOINT, data=payload, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with urlopen(request, timeout=30) as response:
            status = response.status
    except HTTPError as error:
        status = error.code
    except URLError as error:
        raise SystemExit(f"IndexNow request failed: {error.reason}")
    print(f"IndexNow HTTP {status}: {len(urls)} URL(s) submitted")
    if status not in (200, 202):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
