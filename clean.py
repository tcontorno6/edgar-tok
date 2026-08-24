#!/usr/bin/env python3
"""clean.py — EDGAR primary documents (iXBRL / HTML) -> plain-text corpus.

Phase 1 cleaner for the edgar-tok tokenizer project. Design notes and every
vocabulary-affecting judgment call live in DECISIONS.md (D-001..D-011).

Pipeline per document:
  1. decode bytes: strict UTF-8, then cp1252 fallback (D-004)
  2. parse with selectolax (Modest engine)
  3. drop <script>, <style>, <head> (D-009), and style="display:none" subtrees (D-007)
  4. walk the DOM emitting text; newlines at block tags only, spaces between
     table cells, nothing at inline boundaries -- so ix:* wrapped numbers stay
     inside their sentence (D-003)
  5. per line: replace NBSP with space (D-002), collapse horizontal whitespace
  6. drop Table-of-Contents lines, page-number lines (arabic + short roman,
     D-010), and repeated short lines (running headers): len < --header-max-len
     and count > --header-min-repeats within the document
  7. collapse blank-line runs to one; skip doc entirely if result < --min-chars
  8. optional --normalize-unicode (OFF by default, D-001)

Output: one .txt per input (same stem) + manifest.csv.

Usage (Windows, from edgar-tok):
  python clean.py --input ..\\ma-target-screener\\data\\filings\\stage2 --output data\\clean
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import time
from collections import Counter
from multiprocessing import Pool, cpu_count
from pathlib import Path

from selectolax.parser import HTMLParser

log = logging.getLogger("clean")

# ---------------------------------------------------------------------------
# Extraction (D-003): newline at block boundaries, space between table cells,
# nothing at inline boundaries. Tags not listed (span, b, i, a, font, ix:*,
# sup, sub, ...) are inline by default, which is what preserves
# "revenues of $3,232,193 for fiscal 2023" as one line.
# ---------------------------------------------------------------------------

BLOCK_TAGS = frozenset({
    "p", "div", "tr", "table", "thead", "tbody", "tfoot", "caption",
    "li", "ul", "ol", "dl", "dt", "dd",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "br", "hr", "blockquote", "pre", "center", "section", "article",
    "header", "footer", "form", "fieldset",
})
CELL_TAGS = frozenset({"td", "th"})
DROP_SELECTORS = ("script", "style", "head", "noscript")  # D-009

_DISPLAY_NONE = re.compile(r"display\s*:\s*none", re.I)

# --- line filters ----------------------------------------------------------
# ToC: a line that IS "Table of Contents" (optionally with a trailing page
# number / index dots), not a line merely mentioning it.
_TOC_LINE = re.compile(r"^\s*table\s+of\s+contents\s*[.\s\d]*$", re.I)
# Page numbers: optional dashes/dots around a bare 1-4 digit number, optional
# "Page"/"F-"/"S-" prefixes (financial-statement pages are F-1, F-2, ...).
# Case-insensitive: "Page 21" and "page 21" are both layout junk (D-010).
_PAGE_LINE = re.compile(r"^\s*[-–—.\s]*((page|pg\.?)\s*)?[FS]?-?\d{1,4}\s*[-–—.\s]*$", re.I)
# Short roman-numeral pages (i, ii, ... xv). [ivx] only, so words like "mix"
# never match (D-010).
_ROMAN_LINE = re.compile(r"^\s*[ivxIVX]{1,5}\s*$")
_HWS = re.compile(r"[ \t\f\v]+")

# --- optional normalization (D-001: OFF by default) ------------------------
_NORMALIZE_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "―": "-", "‑": "-",
    "…": "...",
    "′": "'", "″": '"',
    # NOTE: section sign (§) is deliberately NOT mapped — no faithful ASCII
    # equivalent exists; see DECISIONS.md D-001.
}


def decode_bytes(raw: bytes) -> tuple[str, str]:
    """Strict UTF-8 first, cp1252 fallback (never fails). See D-004."""
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace"), "cp1252"


_SGML_HEAD = re.compile(r"(?is)<DOCUMENT>\s*<TYPE>")
_SGML_TEXT_OPEN = re.compile(r"(?i)<TEXT>")


def strip_sgml_wrapper(html: str) -> tuple[str, bool]:
    """305/358 seed files are EDGAR SGML-wrapped:
        <DOCUMENT><TYPE>SC 13D/A<SEQUENCE>1<FILENAME>x.htm<DESCRIPTION>...<TEXT> <html>...
    Those TYPE/FILENAME/DESCRIPTION fields render as junk lines at the top of
    the cleaned text. When the wrapper is present, keep only what is between
    the first <TEXT> and the last </TEXT> (D-011). No-op for clean documents.
    """
    if not _SGML_HEAD.search(html[:512]):
        return html, False
    m = _SGML_TEXT_OPEN.search(html[:4096])
    if not m:
        return html, False
    body = html[m.end():]
    end = body.upper().rfind("</TEXT>")
    return (body[:end] if end != -1 else body), True


def extract_text(html: str) -> str:
    """DOM -> raw text with block-structure newlines (D-003, D-007, D-009)."""
    tree = HTMLParser(html)
    for sel in DROP_SELECTORS:
        for node in tree.css(sel):
            node.decompose()
    for node in tree.css("[style]"):
        if _DISPLAY_NONE.search(node.attributes.get("style") or ""):
            node.decompose()

    root = tree.body if tree.body is not None else tree.root
    if root is None:
        return ""
    parts: list[str] = []
    for node in root.traverse(include_text=True):
        tag = node.tag
        if tag == "-text":
            t = node.text_content
            if t:
                parts.append(t)
        elif tag in BLOCK_TAGS:
            parts.append("\n")
        elif tag in CELL_TAGS:
            parts.append(" ")
    return "".join(parts)


def filter_lines(
    text: str, header_max_len: int, header_min_repeats: int
) -> tuple[str, dict[str, int]]:
    """Whitespace normalization + the three line filters. Returns cleaned text
    and per-filter drop counts for the manifest notes."""
    # NBSP -> space happens before horizontal-whitespace collapse (D-002)
    lines = [_HWS.sub(" ", ln.replace("\xa0", " ")).strip() for ln in text.split("\n")]

    # Count line frequency for the running-header filter (non-empty lines only)
    freq = Counter(ln for ln in lines if ln)

    dropped = {"toc": 0, "page": 0, "header": 0}
    kept: list[str] = []
    for ln in lines:
        if not ln:
            kept.append("")
            continue
        if _TOC_LINE.match(ln):
            dropped["toc"] += 1
            continue
        if _PAGE_LINE.match(ln) or _ROMAN_LINE.match(ln):
            dropped["page"] += 1
            continue
        if len(ln) < header_max_len and freq[ln] > header_min_repeats:
            dropped["header"] += 1
            continue
        kept.append(ln)

    # Collapse blank runs to a single blank line
    out: list[str] = []
    blank = False
    for ln in kept:
        if ln:
            out.append(ln)
            blank = False
        elif not blank and out:
            out.append("")
            blank = True
    while out and not out[-1]:
        out.pop()
    return "\n".join(out), dropped


def normalize_unicode(text: str) -> str:
    return text.translate(str.maketrans(_NORMALIZE_MAP))


_STEM = re.compile(r"^(?P<cik>\d{10})_(?P<accession>\d{18})_(?P<form>[A-Za-z0-9-]+)$")


def clean_one(job: tuple[str, str, dict]) -> dict:
    """Worker: clean one file, write output, return a manifest row."""
    in_path, out_dir, opt = job
    src = Path(in_path)
    row = {
        "filename": src.name, "cik": "", "accession": "", "form": "",
        "raw_bytes": 0, "clean_bytes": 0, "compression_ratio": "",
        "status": "", "encoding": "", "notes": "",
    }
    m = _STEM.match(src.stem)
    if m:
        row.update(cik=m["cik"], accession=m["accession"], form=m["form"])
    try:
        raw = src.read_bytes()
        row["raw_bytes"] = len(raw)
        html, enc = decode_bytes(raw)
        row["encoding"] = enc
        html, wrapped = strip_sgml_wrapper(html)

        text = extract_text(html)
        text, dropped = filter_lines(
            text, opt["header_max_len"], opt["header_min_repeats"]
        )
        if opt["normalize_unicode"]:
            text = normalize_unicode(text)

        clean_bytes = len(text.encode("utf-8"))
        row["clean_bytes"] = clean_bytes
        row["compression_ratio"] = (
            round(clean_bytes / len(raw), 4) if raw else 0
        )
        row["notes"] = (
            f"dropped_lines toc={dropped['toc']} page={dropped['page']} "
            f"header={dropped['header']}"
        )
        if wrapped:
            row["notes"] += "; sgml_wrapper_stripped"
        if len(text) < opt["min_chars"]:
            row["status"] = "skipped_short"
            row["notes"] += f"; cleaned len {len(text)} < min_chars {opt['min_chars']}"
            return row

        (Path(out_dir) / f"{src.stem}.txt").write_text(text, encoding="utf-8")
        row["status"] = "ok"
    except Exception as exc:  # never let one bad file kill the run
        row["status"] = "error"
        row["notes"] = f"{type(exc).__name__}: {exc}"
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--input", required=True, type=Path, help="dir of .htm filings")
    ap.add_argument("--output", required=True, type=Path, help="dir for cleaned .txt")
    ap.add_argument("--workers", type=int, default=cpu_count(),
                    help=f"parallel workers (default: all cores = {cpu_count()} here)")
    ap.add_argument("--min-chars", type=int, default=5000,
                    help="skip docs whose cleaned text is shorter than this (default 5000)")
    ap.add_argument("--header-max-len", type=int, default=80,
                    help="running-header filter: only lines shorter than this (default 80)")
    ap.add_argument("--header-min-repeats", type=int, default=5,
                    help="running-header filter: drop lines repeating more than this many times (default 5)")
    ap.add_argument("--normalize-unicode", action="store_true",
                    help="map curly quotes/dashes/ellipsis to ASCII (OFF by default; see DECISIONS.md D-001)")
    ap.add_argument("--manifest", type=Path, default=None,
                    help="manifest CSV path (default: <output>/manifest.csv)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    files = sorted(args.input.glob("*.htm")) + sorted(args.input.glob("*.html"))
    if not files:
        log.error("no .htm/.html files found in %s", args.input)
        return 1
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.manifest or (args.output / "manifest.csv")

    opt = {
        "min_chars": args.min_chars,
        "header_max_len": args.header_max_len,
        "header_min_repeats": args.header_min_repeats,
        "normalize_unicode": args.normalize_unicode,
    }
    jobs = [(str(p), str(args.output), opt) for p in files]

    t0 = time.time()
    workers = max(1, min(args.workers, len(jobs)))
    log.info("cleaning %d files with %d workers ...", len(jobs), workers)
    if workers == 1:
        rows = [clean_one(j) for j in jobs]
    else:
        with Pool(workers) as pool:
            rows = list(pool.imap_unordered(clean_one, jobs, chunksize=4))

    rows.sort(key=lambda r: r["filename"])
    with manifest_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    ok = [r for r in rows if r["status"] == "ok"]
    short = [r for r in rows if r["status"] == "skipped_short"]
    err = [r for r in rows if r["status"] == "error"]
    raw_total = sum(r["raw_bytes"] for r in rows)
    clean_total = sum(r["clean_bytes"] for r in ok)
    log.info("done in %.1fs: %d ok, %d skipped_short, %d error",
             time.time() - t0, len(ok), len(short), len(err))
    log.info("bytes: %.1f MB raw -> %.1f MB clean (%.1f%% survival on ok docs)",
             raw_total / 1e6, clean_total / 1e6,
             100 * clean_total / max(1, sum(r["raw_bytes"] for r in ok)))
    for r in short:
        log.info("  skipped_short: %s (%s)", r["filename"], r["notes"])
    for r in err:
        log.warning("  error: %s (%s)", r["filename"], r["notes"])
    log.info("manifest: %s", manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
