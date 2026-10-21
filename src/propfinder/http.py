"""Small download helpers with retries."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from propfinder.config import USER_AGENT

log = logging.getLogger(__name__)

session = requests.Session()
session.headers["User-Agent"] = USER_AGENT


def download(url: str, target: Path, timeout: int = 300, attempts: int = 3) -> Path:
    """Stream a URL to disk. A partial file never replaces a complete one."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    for attempt in range(1, attempts + 1):
        try:
            with session.get(url, stream=True, timeout=timeout) as response:
                response.raise_for_status()
                with tmp.open("wb") as fh:
                    for chunk in response.iter_content(chunk_size=1 << 20):
                        fh.write(chunk)
            tmp.replace(target)
            log.info("downloaded %s (%.1f MB)", target.name, target.stat().st_size / 1e6)
            return target
        except requests.RequestException as exc:
            if attempt == attempts:
                raise
            log.warning("download of %s failed (%s), retrying", url, exc)
            time.sleep(5 * attempt)
    raise AssertionError("unreachable")


def exists(url: str) -> bool:
    try:
        response = session.head(url, timeout=60, allow_redirects=True)
        return response.status_code == 200
    except requests.RequestException:
        return False


def last_modified(url: str) -> str | None:
    try:
        response = session.head(url, timeout=60, allow_redirects=True)
        return response.headers.get("Last-Modified") if response.ok else None
    except requests.RequestException:
        return None


def get_text(url: str, timeout: int = 60) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def post_json(url: str, data: dict, timeout: int = 300) -> dict:
    response = session.post(url, data=data, timeout=timeout, headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()
