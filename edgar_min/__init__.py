"""edgar_min — minimal EDGAR client, vendored from ma-target-screener.

Source: ma-target-screener/src/mascreener/edgar/{client,filings,models}.py
(Tyler's own battle-tested code; see edgar-tok/docs/FETCHER.md). Changes made
while vendoring:
  * mascreener.config dependency removed — EdgarClient now takes explicit
    constructor arguments (user_agent, cache_dir, requests_per_sec).
  * company_tickers() and full_text_search() dropped (unused here).
  * Everything else (token bucket, tenacity retries, sha-keyed disk cache,
    idempotent download_document, columnar submissions parsing) is unchanged.
"""

from edgar_min.client import EdgarClient, EdgarError
from edgar_min.filings import iter_filings
from edgar_min.models import Filing, pad_cik

__all__ = ["EdgarClient", "EdgarError", "Filing", "iter_filings", "pad_cik"]
