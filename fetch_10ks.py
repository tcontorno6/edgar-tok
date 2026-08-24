#!/usr/bin/env python3
"""fetch_10ks.py — expand the edgar-tok corpus with 3,000–5,000 additional 10-Ks.

Strategy (see docs/FETCHER.md §5 and DECISIONS.md D-013):
  1. CHOOSE offline: walk SEC quarterly master indexes for --years, collect
     every 10-K row, drop accessions already in the seed corpus, then sample
     with per-year quotas and at most ONE filing per company (seeded,
     reproducible).
  2. RESOLVE: one submissions() call per company -> primary document URL.
  3. DOWNLOAD: idempotent, rate-limited (8 req/s, SEC cap is 10), into
     --out as {cik}_{accession}_10K.htm — the same naming as the seed corpus.

Resumable by design: every filing's outcome is appended to
--out/fetch_manifest.csv immediately; re-running skips anything already
resolved, and download_document() skips files already on disk. Failures are
logged, never fatal. Ctrl-C is safe — just re-run to continue.

Typical overnight run (PowerShell, from edgar-tok, venv active):
  $env:EDGAR_USER_AGENT = "Tyler Contorno tyler.contorno1234@gmail.com"
  python fetch_10ks.py --target 4000 --index-cache-src ..\\ma-target-screener\\data\\cache\\edgar

Smoke test first:
  python fetch_10ks.py --dry-run --index-cache-src ..\\ma-target-screener\\data\\cache\\edgar
  python fetch_10ks.py --limit 3  --index-cache-src ..\\ma-target-screener\\data\\cache\\edgar
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from edgar_min import EdgarClient, iter_filings, pad_cik
from edgar_min.client import BASE_WWW

log = logging.getLogger("fetch")

MANIFEST_FIELDS = ["cik", "accession", "filed", "year", "form", "company",
                   "status", "bytes", "url", "note"]
# statuses that should NOT be retried on resume (add "error" via --retry-errors=False default)
DONE_STATUSES = {"ok", "ok_existing", "no_primary_doc", "no_match"}


@dataclass(frozen=True)
class IndexRow:
    cik: str          # 10-digit padded
    company: str
    filed: str        # YYYY-MM-DD
    accession: str    # dashed, e.g. 0001193125-16-624286
    form: str = "10-K"  # exact EDGAR form string

    @property
    def accession_nodash(self) -> str:
        return self.accession.replace("-", "")

    @property
    def year(self) -> int:
        return int(self.filed[:4])

    @property
    def form_tag(self) -> str:
        """Filename-safe form: '10-K'->'10K', 'DEF 14A'->'DEF14A' (matches the
        existing corpus convention)."""
        return re.sub(r"[^A-Za-z0-9]", "", self.form)


# ---------------------------------------------------------------- indexes --

def load_master_index(
    client: EdgarClient | None, year: int, qtr: int,
    cache_dir: Path, cache_src: Path | None,
) -> list[str]:
    """Quarterly master.idx lines: from --index-cache-src (read-only, e.g. the
    old project's 60 cached files), else from --cache, else fetched and cached.
    Returns [] on failure (a missing quarter shouldn't kill the run)."""
    name = f"master_{year}_QTR{qtr}.idx"
    for d in filter(None, (cache_src, cache_dir)):
        p = Path(d) / name
        if p.exists() and p.stat().st_size > 0:
            return p.read_text(encoding="utf-8", errors="replace").splitlines()
    if client is None:  # --dry-run never touches the network
        log.warning("index %s not cached and --dry-run set — skipping", name)
        return []
    url = f"{BASE_WWW}/Archives/edgar/full-index/{year}/QTR{qtr}/master.idx"
    try:
        raw = client.get_bytes(url)
    except Exception as exc:
        log.warning("index %s fetch failed: %s", name, exc)
        return []
    dest = Path(cache_dir) / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return raw.decode("utf-8", errors="replace").splitlines()


def parse_index_rows(lines: list[str], forms: frozenset[str]) -> list[IndexRow]:
    """master.idx body: CIK|Company Name|Form Type|Date Filed|Filename.
    Form filter is an exact-string match against EDGAR form names — amendments
    ('10-K/A') are separate strings and excluded unless requested (D-013)."""
    out: list[IndexRow] = []
    in_body = False
    for line in lines:
        if not in_body:
            if line.startswith("---"):
                in_body = True
            continue
        parts = line.split("|")
        if len(parts) != 5:
            continue
        cik_raw, name, form, filed, fname = (p.strip() for p in parts)
        if form not in forms:
            continue
        m = re.search(r"(\d{10}-\d{2}-\d{6})\.txt$", fname)
        if not m or not re.match(r"^\d{4}-\d{2}-\d{2}$", filed):
            continue
        try:
            out.append(IndexRow(pad_cik(cik_raw), name, filed, m.group(1), form))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------- sampling --

def sample_rows(
    rows: list[IndexRow], target: int, years: list[int],
    exclude_accessions: set[str], seed: int,
) -> list[IndexRow]:
    """Per-year quotas, at most one filing per CIK, seeded shuffle (D-013).
    A second pass redistributes quota that thin years couldn't fill."""
    rng = random.Random(seed)
    by_year: dict[int, list[IndexRow]] = defaultdict(list)
    for r in rows:
        if r.year in years and r.accession_nodash not in exclude_accessions:
            by_year[r.year].append(r)
    for lst in by_year.values():
        rng.shuffle(lst)

    quota = max(1, target // len(years))
    picked: list[IndexRow] = []
    used_ciks: set[str] = set()

    def take(year: int, n: int) -> int:
        got = 0
        for r in by_year.get(year, []):
            if got >= n or len(picked) >= target:
                break
            if r.cik in used_ciks:
                continue
            used_ciks.add(r.cik)
            picked.append(r)
            got += 1
        return got

    for year in years:                       # pass 1: even quotas
        take(year, quota)
    for year in years:                       # pass 2: fill remainder
        if len(picked) >= target:
            break
        take(year, target - len(picked))
    return picked


# ---------------------------------------------------------------- manifest --

def load_manifest(path: Path) -> dict[str, str]:
    """accession_nodash -> status from a previous run (resume support)."""
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as fh:
        return {row["accession"]: row["status"] for row in csv.DictReader(fh)}


class ManifestWriter:
    """Append-mode CSV, flushed per row so a crash loses nothing."""

    def __init__(self, path: Path) -> None:
        new = not path.exists()
        self._fh = path.open("a", newline="", encoding="utf-8")
        self._w = csv.DictWriter(self._fh, fieldnames=MANIFEST_FIELDS)
        if new:
            self._w.writeheader()

    def write(self, **row) -> None:
        self._w.writerow({k: row.get(k, "") for k in MANIFEST_FIELDS})
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


# -------------------------------------------------------------------- main --

def parse_years(spec: str) -> list[int]:
    m = re.match(r"^(\d{4})-(\d{4})$", spec)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return list(range(a, b + 1))
    return sorted(int(y) for y in spec.split(","))


def main() -> int:
    ap = argparse.ArgumentParser(description="Bulk-fetch 10-K primary documents for the tokenizer corpus.")
    ap.add_argument("--target", type=int, default=4000, help="filings to fetch (default 4000)")
    ap.add_argument("--forms", default="10-K",
                    help="comma-separated exact EDGAR form names, e.g. "
                         "'10-Q,8-K,DEF 14A' (default 10-K). With multiple "
                         "forms the target is split evenly per form.")
    ap.add_argument("--years", default="2013-2024",
                    help="'2013-2024' or '2015,2018,2021' (default 2013-2024)")
    ap.add_argument("--seed", type=int, default=42, help="sampling seed (default 42)")
    ap.add_argument("--user-agent", default=os.environ.get("EDGAR_USER_AGENT", ""),
                    help="'Name email' — REQUIRED by SEC (default: env EDGAR_USER_AGENT)")
    ap.add_argument("--out", type=Path, default=Path("data/raw"))
    ap.add_argument("--cache", type=Path, default=Path("data/cache/edgar"),
                    help="edgar-tok's own cache dir (writable)")
    ap.add_argument("--index-cache-src", type=Path, default=None,
                    help=r"read-only extra index location, e.g. ..\ma-target-screener\data\cache\edgar "
                         "(reuses the 60 already-downloaded master indexes; never written to)")
    ap.add_argument("--exclude-manifest", type=Path, default=Path("data/clean/manifest.csv"),
                    help="seed-corpus manifest; its accessions are excluded (default data/clean/manifest.csv)")
    ap.add_argument("--rps", type=float, default=8.0, help="requests/second (SEC cap 10; default 8)")
    ap.add_argument("--limit", type=int, default=None, help="cap the sample (smoke tests)")
    ap.add_argument("--dry-run", action="store_true",
                    help="selection only — no network, prints the per-year plan")
    ap.add_argument("--retry-errors", action="store_true",
                    help="re-attempt filings whose previous status was 'error'")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    years = parse_years(args.years)

    # exclusions: seed corpus + previous fetch outcomes
    exclude: set[str] = set()
    if args.exclude_manifest and args.exclude_manifest.exists():
        with args.exclude_manifest.open(newline="", encoding="utf-8") as fh:
            exclude = {r["accession"] for r in csv.DictReader(fh) if r.get("accession")}
        log.info("excluding %d seed-corpus accessions (%s)", len(exclude), args.exclude_manifest)

    client = None
    if not args.dry_run:
        client = EdgarClient(user_agent=args.user_agent, cache_dir=args.cache,
                             requests_per_sec=args.rps)

    # 1. CHOOSE ---------------------------------------------------------------
    forms = [f.strip() for f in args.forms.split(",") if f.strip()]
    formset = frozenset(forms)
    all_rows: list[IndexRow] = []
    for year in years:
        for qtr in (1, 2, 3, 4):
            lines = load_master_index(client, year, qtr, args.cache, args.index_cache_src)
            all_rows.extend(parse_index_rows(lines, formset))
        log.info("indexes %d: %d cumulative matching rows", year, len(all_rows))

    # per-form sampling: without it, high-volume forms (8-K) would swamp the
    # sample; CIK-dedupe applies within each form (D-020)
    per_form_target = max(1, args.target // len(forms))
    picked: list[IndexRow] = []
    for fm in forms:
        picked.extend(sample_rows([r for r in all_rows if r.form == fm],
                                  per_form_target, years, exclude, args.seed))
    if args.limit:
        picked = picked[: args.limit]

    per_year = Counter(r.year for r in picked)
    per_form = Counter(r.form for r in picked)
    log.info("selected %d filings across %d companies: %s",
             len(picked), len({(r.cik, r.form) for r in picked}), dict(per_form))
    for y in years:
        log.info("  %d: %5d available -> %4d selected",
                 y, sum(1 for r in all_rows if r.year == y), per_year.get(y, 0))

    if args.dry_run:
        log.info("dry run — stopping before any network resolution.")
        return 0

    # 2+3. RESOLVE + DOWNLOAD -------------------------------------------------
    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / "fetch_manifest.csv"
    prior = load_manifest(manifest_path)
    skip_statuses = DONE_STATUSES | (set() if args.retry_errors else {"error"})
    todo = [r for r in picked if prior.get(r.accession_nodash) not in skip_statuses]
    log.info("resume: %d already handled, %d to do", len(picked) - len(todo), len(todo))
    log.info("estimated requests ~%d (submissions + documents); at %.0f req/s "
             "budget that's ~%.0f min of request time — bandwidth will dominate",
             2 * len(todo), args.rps, 2 * len(todo) / args.rps / 60)

    mw = ManifestWriter(manifest_path)
    counts = Counter()
    t0 = time.time()
    try:
        for i, r in enumerate(todo, 1):
            dest = args.out / f"{r.cik}_{r.accession_nodash}_{r.form_tag}.htm"
            base = dict(cik=r.cik, accession=r.accession_nodash, filed=r.filed,
                        year=r.year, form=r.form, company=r.company)
            try:
                if dest.exists() and dest.stat().st_size > 0:
                    counts["ok_existing"] += 1
                    mw.write(**base, status="ok_existing", bytes=dest.stat().st_size)
                    continue
                # find this accession in the company's submissions feed
                filed_d = date.fromisoformat(r.filed)
                match = None
                for f in iter_filings(client, r.cik, forms=frozenset({r.form}),
                                      since=filed_d):
                    if f.accession_nodash == r.accession_nodash:
                        match = f
                        break
                if match is None:
                    counts["no_match"] += 1
                    mw.write(**base, status="no_match",
                             note="accession not in submissions feed")
                    continue
                if not match.primary_doc_url:
                    counts["no_primary_doc"] += 1
                    mw.write(**base, status="no_primary_doc",
                             note="paper/old filing without primaryDocument")
                    continue
                client.download_document(match.primary_doc_url, dest)
                counts["ok"] += 1
                mw.write(**base, status="ok", bytes=dest.stat().st_size,
                         url=match.primary_doc_url)
            except Exception as exc:
                counts["error"] += 1
                mw.write(**base, status="error", note=f"{type(exc).__name__}: {exc}")
                log.warning("[%d/%d] %s error: %s", i, len(todo), r.accession, exc)

            if i % 25 == 0 or i == len(todo):
                el = time.time() - t0
                eta = el / i * (len(todo) - i)
                log.info("[%d/%d] ok=%d exist=%d err=%d nomatch=%d nodoc=%d | %.0fs elapsed, ~%.0f min left",
                         i, len(todo), counts["ok"], counts["ok_existing"], counts["error"],
                         counts["no_match"], counts["no_primary_doc"], el, eta / 60)
    except KeyboardInterrupt:
        log.warning("interrupted — progress is saved; re-run the same command to resume.")
        return 130
    finally:
        mw.close()
        if client:
            client.close()

    log.info("done in %.1f min: %s", (time.time() - t0) / 60, dict(counts))
    log.info("manifest: %s", manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
