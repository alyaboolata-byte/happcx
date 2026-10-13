#!/usr/bin/env python3
"""Submit sitemap URLs for the configured sites to IndexNow (Yandex/Bing network)."""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ENDPOINT = "https://api.indexnow.org/indexnow"
CONFIG = Path(__file__).with_name("sites.json")
TIMEOUT = 25
MAX_URLS_PER_REQUEST = 10_000
KEY_PATTERN = re.compile(r"^[a-fA-F0-9]{8,128}$")


def get(url):
    request = Request(url, headers={"User-Agent": "IndexNow-site-notifier/1.0"})
    with urlopen(request, timeout=TIMEOUT) as response:
        if response.status != 200:
            raise RuntimeError(f"GET {url} returned HTTP {response.status}")
        return response.read()


def sitemap_urls(host):
    """Read a sitemap or sitemap index and keep only canonical URLs for this host."""
    pending = [f"https://{host}/sitemap.xml"]
    visited_sitemaps = set()
    urls = []
    while pending:
        sitemap_url = pending.pop()
        if sitemap_url in visited_sitemaps:
            continue
        visited_sitemaps.add(sitemap_url)
        root = ET.fromstring(get(sitemap_url))
        kind = root.tag.rsplit("}", 1)[-1]
        if kind not in {"urlset", "sitemapindex"}:
            raise RuntimeError(f"Unexpected sitemap root in {sitemap_url}: {kind}")
        for node in root:
            loc = next((child.text.strip() for child in node if child.tag.rsplit("}", 1)[-1] == "loc" and child.text), None)
            if not loc:
                continue
            if kind == "sitemapindex":
                if urlparse(loc).hostname != host:
                    raise RuntimeError(f"Sitemap index points outside {host}: {loc}")
                pending.append(loc)
                continue
            parsed = urlparse(loc)
            if parsed.scheme != "https" or parsed.netloc != host:
                raise RuntimeError(f"Sitemap URL does not belong to https://{host}: {loc}")
            urls.append(loc)
            if len(urls) > MAX_URLS_PER_REQUEST * 100:
                raise RuntimeError(f"Sitemap for {host} exceeds the safety limit")
    return list(dict.fromkeys(urls))


def submit(site):
    host = site["host"]
    key_location = f"https://{host}{site['keyPath']}"
    key = get(key_location).decode("utf-8").strip()
    if not KEY_PATTERN.fullmatch(key):
        raise RuntimeError(f"Key file at {key_location} must contain 8–128 hexadecimal characters")

    urls = sitemap_urls(host)
    if not urls:
        raise RuntimeError(f"No URLs found in https://{host}/sitemap.xml")

    statuses = []
    for start in range(0, len(urls), MAX_URLS_PER_REQUEST):
        batch = urls[start : start + MAX_URLS_PER_REQUEST]
        payload = json.dumps({
            "host": host,
            "key": key,
            "keyLocation": key_location,
            "urlList": batch,
        }).encode("utf-8")
        request = Request(
            ENDPOINT,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=TIMEOUT) as response:
                statuses.append(response.status)
        except HTTPError as error:
            statuses.append(error.code)
    if any(status not in (200, 202) for status in statuses):
        raise RuntimeError(f"IndexNow returned {statuses} for {host} ({len(urls)} URL(s))")
    print(f"{host}: IndexNow HTTP {statuses}; {len(urls)} URL(s) submitted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", action="append", help="Submit one host; repeat to select multiple. Defaults to all configured hosts.")
    args = parser.parse_args()
    sites = json.loads(CONFIG.read_text(encoding="utf-8"))
    available = {site["host"]: site for site in sites}
    selected = args.site or list(available)
    unknown = [host for host in selected if host not in available]
    if unknown:
        parser.error("Unknown host(s): " + ", ".join(unknown))

    failures = []
    for host in selected:
        try:
            submit(available[host])
        except (OSError, ET.ParseError, RuntimeError, UnicodeError) as error:
            failures.append((host, error))
            print(f"{host}: ERROR: {error}", file=sys.stderr)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
