#!/usr/bin/env python3
"""inspect_corpus.py — report on the cleaned EDGAR corpus.

Reads data/clean/*.txt (or --corpus DIR) and prints:
  * size stats: file count, MB, mean/median/p10/p90 document length
  * rough token estimate (chars / 4)
  * character composition: % letters / digits / punctuation / whitespace
  * counts + per-million-char rates for the domain patterns this tokenizer
    project is about (CUSIPs, dollar amounts, percentages, bps, $TICKERs,
    rule/section citations, surviving us-gaap:/ix: leakage)
  * junk hunt: most frequent surviving lines corpus-wide (residual
    boilerplate), very long lines, ratio outliers from the manifest
  * a 40-line random sample from one document for eyeballing

Usage:
  python inspect_corpus.py --corpus data\\clean --manifest data\\clean\\manifest.csv
"""

from __future__ import annotations

import argparse
import csv
import random
import re
import statistics as st
import sys
import unicodedata
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# Domain patterns. Notes:
#  * CUSIPs are 9 chars (8 base + check digit). Many are all-digit and
#    indistinguishable from plain 9-digit numbers, so we report two measures:
#    the "CUSIP" keyword (ground truth anchor: 13Ds label them) and 9-char
#    alphanumeric tokens that contain at least one letter (high-precision).
#  * $TICKER requires letters after $ so dollar amounts never match.
# ---------------------------------------------------------------------------
PATTERNS: dict[str, re.Pattern] = {
    "dollar_amount ($1,234.56 / $77 million)":
        re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?"),
    "percentage (4.25%)":
        re.compile(r"\d+(?:\.\d+)?\s?%"),
    "basis_points (150bps / basis points)":
        re.compile(r"\b\d+\s?bps\b|\bbasis\s+points?\b", re.I),
    "cusip_keyword ('CUSIP')":
        re.compile(r"\bCUSIP\b", re.I),
    "cusip_like (9-char alnum w/ letter, e.g. 88160R101)":
        re.compile(r"\b(?=[0-9A-Z]{9}\b)(?=[0-9A-Z]*[A-Z])[0-9A-Z]{8}[0-9]\b"),
    "ticker_like ($SGRY)":
        re.compile(r"\$[A-Z]{1,5}\b"),
    "rule_section_citation (Rule 206(4)-1, Section 13(d), Item 1A)":
        re.compile(r"\b(?:Rule|Section|Regulation|Item)\s+\d+[\w.()\-]*", re.I),
    "section_symbol (§251(h))":
        re.compile(r"§\s?\d[\w.()\-]*"),
    "us_gaap_leak (us-gaap: — should be ~0)":
        re.compile(r"us-gaap:[A-Za-z]+"),
    "ix_tag_leak (<ix: — should be 0)":
        re.compile(r"</?ix:", re.I),
}


def char_composition(counter: Counter) -> dict[str, int]:
    """Classify the corpus's unique characters once, then sum counts.
    (Counter(text) is C-speed; this avoids a Python loop over 80M chars.)"""
    buckets = {"letters": 0, "digits": 0, "whitespace": 0, "punctuation": 0, "other": 0}
    for ch, n in counter.items():
        if ch.isalpha():
            buckets["letters"] += n
        elif ch.isdigit():
            buckets["digits"] += n
        elif ch.isspace():
            buckets["whitespace"] += n
        elif unicodedata.category(ch).startswith(("P", "S")):
            buckets["punctuation"] += n  # incl. symbols: $ % § — the point of this project
        else:
            buckets["other"] += n
    return buckets


def main() -> int:
    # Windows: redirected stdout defaults to cp1252, which cannot encode the
    # corpus's ☐/þ/§ glyphs and would crash `python inspect_corpus.py > out.txt`.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, default=Path("data/clean"))
    ap.add_argument("--manifest", type=Path, default=None,
                    help="default: <corpus>/manifest.csv")
    ap.add_argument("--sample-lines", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    files = sorted(args.corpus.glob("*.txt"))
    if not files:
        print(f"no .txt files in {args.corpus}", file=sys.stderr)
        return 1

    lengths: dict[str, int] = {}
    char_counter: Counter = Counter()
    pat_counts: Counter = Counter()
    line_freq: Counter = Counter()
    long_lines = 0
    digit_dense_lines = 0

    for p in files:
        text = p.read_text(encoding="utf-8")
        lengths[p.name] = len(text)
        char_counter.update(text)
        for name, pat in PATTERNS.items():
            pat_counts[name] += len(pat.findall(text))
        for ln in text.split("\n"):
            if not ln:
                continue
            line_freq[ln] += 1
            if len(ln) > 2000:
                long_lines += 1
            elif len(ln) > 20 and sum(c.isdigit() for c in ln) / len(ln) > 0.5:
                digit_dense_lines += 1

    total_chars = sum(lengths.values())
    sizes = sorted(lengths.values())
    q = lambda f: sizes[min(len(sizes) - 1, int(len(sizes) * f))]

    print("=" * 72)
    print("CORPUS")
    print("=" * 72)
    print(f"  files:            {len(files)}")
    print(f"  total size:       {total_chars/1e6:.1f}M chars (~{total_chars/1e6:.0f} MB as UTF-8)")
    print(f"  doc length chars: mean {st.mean(sizes):,.0f}  median {int(st.median(sizes)):,}  "
          f"p10 {q(0.10):,}  p90 {q(0.90):,}  min {sizes[0]:,}  max {sizes[-1]:,}")
    print(f"  rough tokens:     ~{total_chars/4/1e6:.1f}M (chars / 4)")

    comp = char_composition(char_counter)
    print("\nCHARACTER COMPOSITION")
    for k, v in comp.items():
        print(f"  {k:<12} {v:>12,}  ({100*v/total_chars:5.2f}%)")
    interesting = ["’", "“", "—", "§", "☐", "þ", "☑"]
    present = {repr(c): char_counter.get(c, 0) for c in interesting}
    print("  notable chars:", "  ".join(f"{k}×{v:,}" for k, v in present.items() if v))

    print("\nDOMAIN PATTERNS (count | per million chars)")
    for name in PATTERNS:
        n = pat_counts[name]
        print(f"  {name:<55} {n:>9,} | {1e6*n/total_chars:8.1f}")

    print("\nJUNK HUNT")
    print(f"  lines >2000 chars (run-on table rows): {long_lines:,}")
    print(f"  digit-dense lines (>50% digits, len>20): {digit_dense_lines:,}")
    print("  top 15 most frequent surviving lines corpus-wide:")
    for ln, n in line_freq.most_common(15):
        print(f"    {n:>5}×  {ln[:100]}")

    manifest = args.manifest or (args.corpus / "manifest.csv")
    if manifest.exists():
        rows = [r for r in csv.DictReader(open(manifest, encoding="utf-8"))
                if r["status"] == "ok"]
        out = [(float(r["compression_ratio"]), r["filename"]) for r in rows]
        odd = [x for x in out if not (0.03 <= x[0] <= 0.45)]
        print(f"  ratio outliers outside [0.03, 0.45]: {len(odd)}")
        for r, f in sorted(odd)[:8]:
            print(f"    {r:.4f}  {f}")

    print("\n" + "=" * 72)
    rng = random.Random(args.seed)
    doc = rng.choice(files)
    lines = [ln for ln in doc.read_text(encoding="utf-8").split("\n")]
    start = rng.randint(0, max(0, len(lines) - args.sample_lines))
    print(f"RANDOM SAMPLE — {doc.name}, lines {start}..{start+args.sample_lines}")
    print("=" * 72)
    for ln in lines[start:start + args.sample_lines]:
        print(f"  | {ln[:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
