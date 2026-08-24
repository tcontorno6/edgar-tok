#!/usr/bin/env python3
"""split_corpus.py — carve a held-out evaluation set before any training.

Why this exists (DECISIONS D-014): the benchmark's compression numbers are
only credible on filings the tokenizer never saw. This script:

  1. collects every cleaned .txt across the given corpus dirs,
  2. content-hashes each document and forces exact duplicates into TRAIN
     (the corpus contains co-registrant twins — an eval doc with a training
     twin would leak),
  3. stratifies by (form, filing-year) and samples --eval-frac of each
     stratum with a fixed seed,
  4. writes data/splits/train_docs.txt and eval_docs.txt (forward-slash
     paths, portable between Windows and POSIX) plus split_stats.json.

Usage (from edgar-tok):
  python split_corpus.py --corpora data\\clean data\\clean_expansion
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

_STEM = re.compile(r"^(?P<cik>\d{10})_(?P<accession>\d{18})_(?P<form>[A-Za-z0-9-]+)$")


def doc_meta(p: Path) -> tuple[str, int]:
    """(form, filing_year) from the {cik}_{accession}_{form} stem.
    Accession digits 10-11 are the 2-digit filing year."""
    m = _STEM.match(p.stem)
    if not m:
        return ("OTHER", 0)
    yy = int(m["accession"][10:12])
    return (m["form"], 2000 + yy)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpora", nargs="+", type=Path,
                    default=[Path("data/clean"), Path("data/clean_expansion")])
    ap.add_argument("--eval-frac", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-dir", type=Path, default=Path("data/splits"))
    args = ap.parse_args()

    files: list[Path] = []
    for d in args.corpora:
        got = sorted(d.glob("*.txt"))
        if not got:
            print(f"WARNING: no .txt files in {d}", file=sys.stderr)
        files.extend(got)
    if not files:
        print("nothing to split", file=sys.stderr)
        return 1

    # --- duplicate detection (content hash) --------------------------------
    by_hash: dict[str, list[Path]] = defaultdict(list)
    for p in files:
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        by_hash[h].append(p)
    dup_groups = {h: ps for h, ps in by_hash.items() if len(ps) > 1}
    dup_paths = {p for ps in dup_groups.values() for p in ps}
    if dup_groups:
        print(f"duplicate content groups: {len(dup_groups)} "
              f"({sum(len(v) for v in dup_groups.values())} files) -> forced into TRAIN")

    # --- stratified sampling ----------------------------------------------
    rng = random.Random(args.seed)
    strata: dict[tuple[str, int], list[Path]] = defaultdict(list)
    for p in files:
        if p in dup_paths:
            continue  # dups go straight to train
        strata[doc_meta(p)].append(p)

    eval_set: set[Path] = set()
    for key in sorted(strata):
        docs = sorted(strata[key])
        rng.shuffle(docs)
        k = int(len(docs) * args.eval_frac)  # floor: tiny strata contribute 0
        eval_set.update(docs[:k])

    # Per-form top-up: a form whose yearly strata are all tiny (13Ds: ~9/yr)
    # would otherwise get ZERO eval docs and the benchmark's per-form slice
    # would be empty. Any form with >=20 docs overall gets at least
    # floor(total * frac) eval docs, topped up from a seeded shuffle.
    by_form: dict[str, list[Path]] = defaultdict(list)
    for key, docs in strata.items():
        by_form[key[0]].extend(docs)
    for fm, docs in sorted(by_form.items()):
        if len(docs) < 20:
            continue
        want = max(1, int(len(docs) * args.eval_frac))
        have = sum(1 for p in eval_set if doc_meta(p)[0] == fm)
        if have < want:
            pool = sorted(p for p in docs if p not in eval_set)
            rng.shuffle(pool)
            eval_set.update(pool[: want - have])

    train = [p for p in files if p not in eval_set]
    evals = sorted(eval_set)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "train_docs.txt").write_text(
        "\n".join(p.as_posix() for p in train) + "\n", encoding="utf-8")
    (args.out_dir / "eval_docs.txt").write_text(
        "\n".join(p.as_posix() for p in evals) + "\n", encoding="utf-8")

    def profile(paths: list[Path]) -> dict:
        forms = Counter(doc_meta(p)[0] for p in paths)
        years = Counter(doc_meta(p)[1] for p in paths)
        return {"docs": len(paths),
                "bytes": sum(p.stat().st_size for p in paths),
                "forms": dict(forms), "years": {str(k): v for k, v in sorted(years.items())}}

    stats = {"seed": args.seed, "eval_frac": args.eval_frac,
             "duplicate_groups": len(dup_groups),
             "train": profile(train), "eval": profile(evals)}
    (args.out_dir / "split_stats.json").write_text(json.dumps(stats, indent=2))

    print(f"TRAIN: {stats['train']['docs']} docs, {stats['train']['bytes']/1e6:.0f} MB")
    print(f"EVAL:  {stats['eval']['docs']} docs, {stats['eval']['bytes']/1e6:.0f} MB "
          f"({100*args.eval_frac:.0f}% target)")
    print(f"eval forms: {stats['eval']['forms']}")
    print(f"lists written to {args.out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
