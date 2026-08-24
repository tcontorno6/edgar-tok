"""Rate-limited, cached, retrying SEC EDGAR HTTP client.

Vendored from ma-target-screener/src/mascreener/edgar/client.py with the
mascreener.config dependency replaced by explicit constructor arguments.
The engine — token bucket, tenacity backoff, sha-keyed cache, idempotent
downloads — is unchanged.

SEC fair-access rules (https://www.sec.gov/os/accessing-edgar-data):
  * Max 10 requests/second — we enforce a token bucket below that (default 8/s).
  * A descriptive User-Agent with contact info is REQUIRED; anonymous clients
    get 403s or throttling.
  * The limiter is per-process: run ONE fetcher at a time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

BASE_DATA = "https://data.sec.gov"
BASE_WWW = "https://www.sec.gov"


class EdgarError(RuntimeError):
    pass


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


class _TokenBucket:
    """Simple thread-safe token bucket: `rate` requests per second."""

    def __init__(self, rate: float) -> None:
        self._rate = rate
        self._capacity = max(1.0, rate)
        self._tokens = self._capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
                self._last = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait = (1 - self._tokens) / self._rate
            time.sleep(wait)


class EdgarClient:
    def __init__(
        self,
        user_agent: str,
        cache_dir: Path,
        requests_per_sec: float = 8.0,
    ) -> None:
        if not user_agent or "@" not in user_agent:
            raise EdgarError(
                "user_agent must be 'Your Name your@email.com' — "
                "the SEC blocks requests without a contact User-Agent."
            )
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._bucket = _TokenBucket(requests_per_sec)
        self._http = httpx.Client(
            headers={
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> EdgarClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ HTTP

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(5),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )
    def _get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        self._bucket.acquire()
        resp = self._http.get(url, params=params)
        resp.raise_for_status()
        return resp

    def _cache_path(self, url: str, params: dict[str, Any] | None = None) -> Path:
        key = url + (json.dumps(params, sort_keys=True) if params else "")
        digest = hashlib.sha256(key.encode()).hexdigest()[:24]
        return self._cache_dir / f"{digest}.json"

    def get_json(
        self, url: str, params: dict[str, Any] | None = None, *, cache: bool = False
    ) -> Any:
        """GET a JSON resource. cache=True only for immutable resources
        (filed documents never change; submissions feeds DO change)."""
        if cache:
            p = self._cache_path(url, params)
            if p.exists():
                return json.loads(p.read_text())
        data = self._get(url, params).json()
        if cache:
            self._cache_path(url, params).write_text(json.dumps(data))
        return data

    def get_bytes(self, url: str) -> bytes:
        return self._get(url).content

    # ------------------------------------------------------- Public endpoints

    def submissions(self, cik: str) -> dict[str, Any]:
        """All filing metadata for a company (recent ~1000 + pointers to older pages)."""
        return self.get_json(f"{BASE_DATA}/submissions/CIK{cik}.json")

    def submissions_page(self, filename: str) -> dict[str, Any]:
        """Older filings overflow into extra pages named in submissions()['filings']['files'].
        These pages are frozen once written — safe to cache."""
        return self.get_json(f"{BASE_DATA}/submissions/{filename}", cache=True)

    def company_facts(self, cik: str) -> dict[str, Any]:
        """All XBRL facts a company ever reported. Kept for the planned
        numerics evaluation set (Phase 3) — one call per company."""
        return self.get_json(f"{BASE_DATA}/api/xbrl/companyfacts/CIK{cik}.json")

    def download_document(self, url: str, dest: Path) -> Path:
        """Download a filed document to disk (idempotent — skips if present)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        dest.write_bytes(self.get_bytes(url))
        return dest
