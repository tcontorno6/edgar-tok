# FETCHER.md — how the ma-target-screener EDGAR fetcher works

*Reverse-engineered 2026-08-23 from `ma-target-screener\src\mascreener\` (read-only).
Every claim below was checked against the source; file references are to that project.*

## TL;DR verdict

**Nothing is broken.** The fetcher is a clean two-layer design, and the layer you
need for edgar-tok — `src\mascreener\edgar\` — has **zero database coupling**. It
needs exactly four things to run: `httpx`, `tenacity`, `pydantic`(+`pydantic-settings`),
and an `EDGAR_USER_AGENT` env var. Everything scary (PostgreSQL, Ollama, the typer
CLI) lives in the *callers*, not in the client.

**Recommendation: revive, don't rewrite — but revive by vendoring.** Copy
`client.py`, `filings.py`, `models.py` (~450 lines total, your own battle-tested
code — it walked all 60 quarterly indexes and thousands of documents without
incident) into edgar-tok, replace the one `mascreener.config` import with ~15
lines of plain env-var reading, and write a small new driver script for the bulk
10-K pull. Standing up PostgreSQL just to reuse the old *pipeline* would be pure
overhead: the DB stores screener state (companies, fingerprints, scores) that a
corpus project doesn't have or need.

---

## 1. The mental model: engine vs. pipeline

```
                    ┌──────────────────────────────────────────────┐
 REUSABLE ENGINE    │  edgar/client.py    EdgarClient              │  no DB
 (what you keep)    │  edgar/filings.py   iter_filings, profile    │  no DB
                    │  edgar/models.py    Filing, CompanyRef       │  no DB
                    │  edgar/facts.py     XBRL → fundamentals      │  no DB
                    └──────────────┬───────────────────────────────┘
                                   │ imported by
                    ┌──────────────▼───────────────────────────────┐
 SCREENER PIPELINE  │  cli.py            `mascreener` typer app    │  ← Postgres
 (what you leave)   │  ingest/pipeline   metadata+docs per ticker  │  ← Postgres
                    │  stage2/documents  10-K/13D text for Claude  │  ← Postgres
                    │  backfill/*        deal discovery, cohorts   │  ← Postgres (mostly)
                    └──────────────────────────────────────────────┘
```

The 358 files in `data\filings\stage2\` were written by **stage2**
(`stage2/documents.py::_download_text`), which is where your filename convention
comes from: `{cik}_{accession-no-dashes}_{10K|13D}.htm`, primary documents only.
(The `ingest --download-docs` path uses a *different* convention —
`data\filings\{TICKER}\{date}_{form}_{accession}.htm` — and was evidently not
used for these files.)

## 2. Public entry points and signatures

### `EdgarClient` (edgar/client.py) — the HTTP engine

```python
EdgarClient(user_agent: str | None = None,     # falls back to EDGAR_USER_AGENT env/.env
            cache_dir: Path | None = None,     # falls back to EDGAR_CACHE_DIR (default data/cache/edgar)
            requests_per_sec: float | None = None)  # falls back to EDGAR_MAX_REQUESTS_PER_SEC (default 8.0)
```

Context manager (`with EdgarClient() as c:`). Methods:

| method | what it hits | notes |
|---|---|---|
| `company_tickers()` | `www.sec.gov/files/company_tickers.json` | full ticker→CIK map, ~10k registrants, never disk-cached |
| `submissions(cik)` | `data.sec.gov/submissions/CIK{cik}.json` | all filing metadata, recent ~1,000 rows + pointers to overflow pages; not cached (it changes) |
| `submissions_page(name)` | `data.sec.gov/submissions/{name}` | older-filings overflow pages; **disk-cached** (immutable) |
| `company_facts(cik)` | `data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` | all XBRL facts ever reported; **not cached** (see §6) |
| `full_text_search(query, forms=None, date_from=None, date_to=None)` | `efts.sec.gov/LATEST/search-index` | EDGAR FTS, covers 2001+ |
| `download_document(url, dest)` | any archives URL | **idempotent**: skips if dest exists non-empty |
| `get_json(url, params, cache=False)` / `get_bytes(url)` | anything | the primitives everything above uses |

### `iter_filings` (edgar/filings.py) — the form/date filter

```python
iter_filings(client, cik,                      # cik as int or str, any padding
             *, forms=DEFAULT_FORMS,           # frozenset of EDGAR form strings
             since: date | None = None,        # lower date bound with early exit
             include_older_pages=True) -> Iterator[Filing]   # newest first
```

`DEFAULT_FORMS = {"10-K", "10-K/A", "10-Q", "8-K", "SC 13D", "SC 13D/A", "DEF 14A", "13F-HR"}`

### `company_profile(client, cik) -> dict` — name/SIC/sector/exchange/ticker from the submissions header.

### `Filing` (edgar/models.py) — the key property

```python
filing.primary_doc_url   # https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}.htm
filing.index_url         # the filing's directory listing
pad_cik(cik)             # anything → canonical 10-digit string
```

### `facts.py` — XBRL numerics (not needed for the corpus, useful for your eval-set idea later)

`annual_series(facts, metric)`, `latest_value(facts, metric)`,
`compute_fundamentals(facts, as_of_year=None, as_of_date=None)` with alias chains
mapping logical metrics ("revenue") to us-gaap tag fallbacks.

### `backfill/discovery.py` — the market-wide bulk pattern (this is your Task 4 blueprint)

```python
_master_index_lines(client, year, qtr)   # quarterly master.idx, disk-cached as master_{y}_QTR{q}.idx
parse_master_index(lines, forms)         # -> [(cik, company_name, form, filed_date), ...]
discover_deals(start_year, end_year, forms)
```

The quarterly **master index** lists *every* filing SEC-wide
(`CIK|Company|Form|Date|Filename`, pipe-delimited). Your 60 cached `.idx` files
(2010–2024) mean a 10-K census of 15 years is already sitting on your disk —
no network needed to *choose* what to fetch.

## 3. Your specific questions, answered

**Can I ask it for 10-Ks specifically? S-4? DEFM14A? 13F?**
Yes — form filtering is an exact string match against EDGAR's own form names,
via three independent routes:

1. *Per company*: `iter_filings(client, cik, forms=frozenset({"10-K"}))`. Any form
   string EDGAR uses is valid: `"S-4"`, `"DEFM14A"`, `"13F-HR"`, `"SC 14D9"`, …
   Mind the exact spelling: `"SC 13D"` has a space; 13F filings are `"13F-HR"`
   (holdings) / `"13F-NT"` (notice); amendments are separate strings (`"10-K/A"`).
2. *Market-wide*: `parse_master_index(lines, frozenset({"10-K"}))` over any
   year/quarter — this is how it found 4,156 merger proxies, and it's the right
   tool for "give me thousands of 10-Ks."
3. *By content*: `full_text_search("strategic alternatives", forms="8-K")`.

**Date-range filtering?** `iter_filings` has `since=` (lower bound, early-exits
walking backward through newest-first feeds — this is what keeps a 500-company
walk fast). There is **no upper bound** in `iter_filings`; callers that need one
(stage2's point-in-time discipline) filter on `filing.filed_date` themselves. The
master-index route is bounded by year/quarter on both ends by construction.
`full_text_search` has both `date_from` and `date_to`.

**Company-list filtering?** Caller-side, three feeders: a plain tickers file
(`load_ticker_file`, one per line, `#` comments), an ETF-holdings CSV
(`parse_holdings_csv` — iShares/SPDR exports), and the reviewed deals CSV. Ticker
resolution (`resolve_tickers`) goes through the live SEC map, so **delisted
companies can't be resolved by ticker** — the master-index route (CIK-native) is
how the project sidestepped that, and your corpus fetch should too.

**Rate limiting / User-Agent?** A thread-safe token bucket at
`EDGAR_MAX_REQUESTS_PER_SEC` (default **8/s**; SEC's cap is 10/s), applied inside
`_get()` so *every* request pays the toll. Retries via tenacity: exponential
backoff 1s→30s, 5 attempts, only on 429/5xx/transport errors, with warning logs.
The constructor **hard-fails** unless the User-Agent contains `@`:
`EdgarError: EDGAR_USER_AGENT must be set to 'Your Name your@email.com'`.
Your `.env.example` documents the exact expected shape. Note the limiter is
per-process — the client's own docstring says run one ingester at a time, and
that constraint carries over to any new fetch script.

**Dedupe / resume from a partial run?**
- *Documents*: `download_document` skips any existing non-empty file → a
  re-run only downloads what's missing. This is real, file-level resumability.
- *Metadata*: `insert_filing` is `ON CONFLICT (accession_no) DO NOTHING`;
  companies are upserted by CIK. Re-ingest is idempotent (DB path only).
- *Immutable HTTP resources*: disk-cached (see next).

**Is data\cache its cache layer, and how is it keyed?** Yes — `data\cache\edgar`
is `EDGAR_CACHE_DIR`, with two distinct populations:
- 1,205 `.json` files keyed `sha256(url + sorted-params-json)[:24].json` —
  written by `get_json(cache=True)`. **Only `submissions_page()` uses the cache
  flag**, so these are submissions *overflow pages* (older filing metadata).
  I opened two and confirmed: columnar `accessionNumber`/`form`/`filingDate`
  arrays. ⚠️ **Correction to your notes:** these are *not* XBRL companyfacts —
  `company_facts()` is never disk-cached (verified: `cache=True` appears exactly
  once in the codebase, in `submissions_page`). The JSONs total only 0.22 GB.
  If you want companyfacts as a numeric-density eval set later, they're one API
  call per company (worth folding into the Task 4 run).
- 60 `.idx` files (`master_{year}_QTR{q}.idx`, 2010–2024) — quarterly master
  indexes cached by `discovery.py` under its own readable naming. These are the
  bulk of the cache by bytes: **1.39 of the 1.61 GB**.

**Python / dependencies?** `requires-python >= 3.11` (your venv ran 3.11 per the
bytecode tags). The edgar package needs only `httpx`, `tenacity`, `pydantic`,
`pydantic-settings` (+ stdlib). The CLI adds `typer` + `rich`; the pipeline adds
`psycopg[binary,pool]` + a live PostgreSQL; stage2 adds `python-dateutil` (+
`anthropic` for the Claude parts). Config comes from `.env` in the *current
working directory* (pydantic-settings), so CLI commands must be run from the
project root.

## 4. Copy-pasteable invocations

All three run against the OLD project untouched, from PowerShell. The package is
installed editable in its venv (the egg-info is from `pip install -e`), so
`mascreener` should be on PATH once the venv is active; if not, re-run
`pip install -e .` inside that venv.

**(a) Health check + a free full-text search (no Postgres needed for the search):**

```powershell
cd C:\Users\Tyler\Desktop\ma-target-screener
.\.venv\Scripts\Activate.ps1
mascreener check          # expect: EDGAR ok; Postgres/Ollama will FAIL unless running — fine
mascreener edgar-search "strategic alternatives" --forms 8-K --date-from 2026-01-01
```

**(b) Library use, standalone — latest 10-K primary-doc URL for one company:**

```powershell
cd C:\Users\Tyler\Desktop\ma-target-screener
.\.venv\Scripts\Activate.ps1
python -c @"
from mascreener.edgar.client import EdgarClient
from mascreener.edgar.filings import iter_filings

with EdgarClient() as c:                      # reads EDGAR_USER_AGENT from .env here
    for f in iter_filings(c, 320193, forms=frozenset({'10-K'})):
        print(f.filed_date, f.accession_no, f.primary_doc_url)
        break
"@
```

**(c) The Task-4 pattern in miniature — count 10-Ks in one cached quarterly index (zero network):**

```powershell
cd C:\Users\Tyler\Desktop\ma-target-screener
.\.venv\Scripts\Activate.ps1
python -c @"
from pathlib import Path
from mascreener.backfill.discovery import parse_master_index

lines = Path('data/cache/edgar/master_2023_QTR1.idx').read_text(errors='replace').splitlines()
rows = parse_master_index(lines, frozenset({'10-K'}))
print(len(rows), '10-Ks filed in 2023 Q1;  first:', rows[0])
"@
```

## 5. What this means for the edgar-tok fetch (Task 4 sketch)

Vendored engine + new ~150-line driver:

1. **Choose** filings offline: parse the 60 already-cached master indexes,
   collect all 10-K rows (~5–8k/year), sample 3–5k across years/CIKs (skipping
   the 249 accessions already in the corpus).
2. **Resolve** each to a primary-document URL (one `submissions()` call per CIK,
   batched by company so it's ~1 metadata request per company, not per filing).
3. **Download** with `download_document()` into `edgar-tok\data\raw\` under the
   existing `{cik}_{accession}_{form}.htm` convention — idempotent, so the
   overnight job resumes by re-running it; failures logged to the manifest and
   skipped, never fatal.

At 8 req/s with ~2 requests per filing net, 4,000 10-Ks ≈ 8,000 requests ≈
**20–30 minutes of request time; the real constraint is bandwidth** (4,000 docs
× ~2 MB median ≈ 8–10 GB) — hence overnight, resumable, on your machine.

## 6. Honest caveats

- `company_facts()` not being disk-cached means your companyfacts-as-eval-set
  idea requires a (cheap) fetch pass — the data is not already on disk.
- `full_text_search` returns the API's first page of hits; the CLI prints 20.
  Fine as a scanner, not built as a bulk harvester — don't use it for Task 4.
- `check` conflates concerns (config+DB+Ollama+EDGAR); expect two red FAILs
  forever in an EDGAR-only workflow. Cosmetic, not a defect.
- The submissions JSON's `primaryDocument` is occasionally empty for very old
  or paper filings → `primary_doc_url is None` → skip and log (your corpus
  already contains one such 291-byte paper stub from the stage2 era, which had
  a different failure mode: stage2 downloaded the placeholder the index pointed
  at).
- pydantic-settings reads `.env` from the CWD — running `mascreener` from
  another directory silently loses your User-Agent config (you'd get the
  hard-fail error). Run from the project root, or export env vars globally.
