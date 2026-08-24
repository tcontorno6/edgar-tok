"""Parse EDGAR submissions feeds into typed Filing records.
Vendored unchanged (minus company_profile) from
ma-target-screener/src/mascreener/edgar/filings.py.

The submissions API returns filings in a column-oriented layout:
    {"filings": {"recent": {"accessionNumber": [...], "form": [...], ...},
                 "files": [{"name": "CIK0000320193-submissions-001.json", ...}]}}
Older filings overflow into the extra pages listed under "files".
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from typing import Any

from edgar_min.client import EdgarClient
from edgar_min.models import Filing, pad_cik

log = logging.getLogger(__name__)

DEFAULT_FORMS = frozenset({"10-K"})


def _rows_from_columnar(cik: str, block: dict[str, Any]) -> Iterator[Filing]:
    accessions = block.get("accessionNumber", [])
    n = len(accessions)
    forms = block.get("form", [""] * n)
    filed = block.get("filingDate", [""] * n)
    period = block.get("reportDate", [""] * n)
    primary = block.get("primaryDocument", [""] * n)
    primary_desc = block.get("primaryDocDescription", [""] * n)
    sizes = block.get("size", [None] * n)

    for i in range(n):
        try:
            yield Filing(
                cik=cik,
                accession_no=accessions[i],
                form_type=forms[i],
                filed_date=filed[i],
                period_of_report=period[i] or None,
                primary_doc=primary[i] or None,
                primary_doc_description=primary_desc[i] or None,
                size_bytes=sizes[i],
            )
        except Exception:  # one malformed row shouldn't kill the run
            log.warning("skipping malformed filing row %s for CIK %s", accessions[i], cik)


def iter_filings(
    client: EdgarClient,
    cik: str | int,
    *,
    forms: frozenset[str] | set[str] = DEFAULT_FORMS,
    since: date | None = None,
    include_older_pages: bool = True,
) -> Iterator[Filing]:
    """Yield a company's filings, newest first, filtered by form type and date.

    since= early-exits the newest-first walk once rows predate the cutoff —
    that's what keeps a multi-thousand-company run fast."""
    cik = pad_cik(cik)
    subs = client.submissions(cik)

    for f in _rows_from_columnar(cik, subs.get("filings", {}).get("recent", {})):
        if since and f.filed_date < since:
            return  # feeds are newest-first; everything after is older
        if f.form_type in forms:
            yield f

    if not include_older_pages:
        return
    for page in subs.get("filings", {}).get("files", []):
        page_data = client.submissions_page(page["name"])
        for f in _rows_from_columnar(cik, page_data):
            if since and f.filed_date < since:
                return
            if f.form_type in forms:
                yield f
