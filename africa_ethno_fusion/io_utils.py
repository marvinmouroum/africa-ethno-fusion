"""Download / cache helpers and the Africa spatial filter."""
from __future__ import annotations

import os
import pathlib

import requests

# Cache downloaded source files so repeated builds don't re-fetch.
CACHE_DIR = pathlib.Path(
    os.environ.get("AFROFUSE_CACHE", pathlib.Path.home() / ".cache" / "afrofuse")
)

# A polite, browser-ish UA. Some hosts (ICR) 403 a bare python UA.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) afrofuse-research/0.1"
)

# Approximate bounding box of the African continent incl. islands
# (minx/lon_min, miny/lat_min, maxx/lon_max, maxy/lat_max).
AFRICA_BBOX = (-26.0, -38.0, 64.0, 38.0)


def cached_download(url: str, filename: str | None = None, force: bool = False) -> pathlib.Path:
    """Download `url` to the cache dir and return the local path (cached)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    filename = filename or url.rsplit("/", 1)[-1].split("?")[0]
    dest = CACHE_DIR / filename
    if dest.exists() and not force and dest.stat().st_size > 0:
        return dest
    resp = requests.get(url, timeout=180, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    content = resp.content
    # Guard against bot-challenge HTML stubs masquerading as a download
    # (Nunn's own host does this; we route around it via GitHub mirrors).
    if content[:512].lstrip().lower().startswith(b"<!doctype html") and not url.endswith(
        (".html", ".geojson", ".json")
    ):
        raise RuntimeError(
            f"{url} returned an HTML page, not a file -- likely a bot challenge. "
            "Use the documented GitHub/mirror URL or pre-download manually."
        )
    dest.write_bytes(content)
    return dest


def clip_africa(gdf):
    """Bounding-box filter to the African continent (fast, approximate)."""
    minx, miny, maxx, maxy = AFRICA_BBOX
    return gdf.cx[minx:maxx, miny:maxy].copy()
